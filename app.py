import os
import pdfplumber
import logging
import hashlib
import json
import nltk
import sqlite3
from nltk.tokenize import sent_tokenize
from flask import Flask, request, jsonify, render_template, Response, stream_with_context, make_response
from dotenv import load_dotenv
from pinecone import ServerlessSpec, Pinecone
from langchain_community.vectorstores import Pinecone as PineconeVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from rank_bm25 import BM25Okapi
from functools import lru_cache
import re
import pandas as pd
import warnings
import google.generativeai as genai
from docx import Document
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime
from langchain.text_splitter import RecursiveCharacterTextSplitter
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from asgiref.wsgi import WsgiToAsgi


# Suppress specific warnings
warnings.filterwarnings("ignore", category=UserWarning, message="WARNING! top_p is not default parameter.")
warnings.filterwarnings("ignore", category=UserWarning, message="WARNING! presence_penalty is not default parameter.")
warnings.filterwarnings("ignore", category=UserWarning, message="WARNING! frequency_penalty is not default parameter.")

# Load environment variables
load_dotenv()

# Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "hr-knowledge-base"
POLICIES_FOLDER = "HR_docs/"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'docx'}

# Add this dictionary after imports
ACRONYM_MAP = {
    "wfh": "work from home policy",
    "pto": "paid time off policy",
    "loa": "leave of absence policy",
    "nda": "non-disclosure agreement",
    "od": "on duty policy",
    "hrbp": "human resources business partner",
    "kra": "KRA Policy - Promoting Transparency",
    "regularization": "Time change Request/ Regularization",
    "regularisation": "Time change Request/ Regularization",
    "posh": "Policy On Prevention of Sexual Harassment",
    "appraisal": "PERFORMANCE APPRAISAL & PROMOTION POLICY",
    "promotion": "PERFORMANCE APPRAISAL & PROMOTION POLICY",
    "prep": "Performance Review & Enhancement Program",
    "Grade": "GRADE STRUCTURE & FLEXIBILITY",
    "leave": "LEAVE POLICY",
    "nda": "Non Compete and Non Disclosure",
    "Office timings": "Office Timing and Attendance Policy",
    "pet": "pet policy",
    "sprint": "Weekly Sprint Policy",
    "work ethics": "WORK PLACE ETHICS"
}

# Standard behavioral questions
QUICK_CHECKS = [
    "Are you willing to relocate if applicable?",
    "What is your notice period?",
    "Can you provide details about your current organization?",
    "Please describe your current role and responsibilities.",
    "What is your current CTC (Cost to Company)?",
    "What is your expected CTC?",
    "What is your educational background?",
    "Can you describe any significant projects you've worked on?",
    "Are there any specific client requirements you want to discuss?",
    "Do you have references from colleagues who might be interested in opportunities with us?"
]

# Prompt templates
input_prompt_template = """
Act as a highly skilled ATS (Applicant Tracking System) specializing in evaluating resumes for job descriptions provided. Your information will be consumed by fellow HR professionals to help them evaluate resumes quickly.

### Task:
Evaluate the provided **resume** against the given **job description**. Consider industry trends and the competitive job market. Prioritize factors based on their relevance to the specific requirements of the job description. All Match Factors should be weighted equally unless otherwise specified in the job description.

### Certification Handling:
* If the job description explicitly mentions required certifications, score the candidate based on whether they possess those certifications.
* If the job description does not mention certifications, consider any relevant certifications the candidate has as a potential bonus, but do not penalize candidates who lack them.
* If a candidate lacks a certification that is explicitly mentioned in the job description, lower the overall score significantly.

### Output:
Return a valid JSON object ONLY. The JSON object MUST have the following keys:

* `"JD Match"` (string): Percentage match (e.g., "85%").
* `"MissingKeywords"` (list): List of missing keywords (can be empty).
* `"Profile Summary"` (string): Summary of strengths and areas for improvement.
* `"Extra Info"` (string): Anything extra that can help the HR to make a decision.
* `"Match Factors"` (object): Breakdown of factors that contributed to the match percentage with individual scores:
    * `"Skills Match"` (number): 0-100 score for technical skills alignment
    * `"Experience Match"` (number): 0-100 score for experience level alignment
    * `"Education Match"` (number): 0-100 score for education requirements match
    * `"Industry Knowledge"` (number): 0-100 score for relevant industry knowledge
    * `"Certification Match"` (number): 0-100 score for relevant certifications
* `"Reasoning"` (string): Explanation of the scoring decision for each "Match Factor" and the overall "JD Match" score.

Do NOT include any additional text, explanations, or formatting outside the JSON object.

---
**Resume:** {resume_text}
**Job Description:** {job_description}
"""

interview_questions_prompt = """
You are an experienced technical recruiter preparing for an interview. Based on the candidate's resume and the job description, generate relevant interview questions.

### Task:
Generate two sets of interview questions - 10 technical questions and 10 non-technical questions that are specifically tailored to assess this candidate for this role.

### Output:
Return a valid JSON object ONLY with the following keys:
* `"TechnicalQuestions"` (array): 10 technical questions related to the candidate's skills and the job requirements.
* `"NonTechnicalQuestions"` (array): 10 behavioral, situational, or cultural fit questions.

Each question should be thoughtful, specific to the resume and job description, and reveal important information about the candidate's suitability.

Do NOT include any additional text, explanations, or formatting outside the JSON object.

---
**Resume:** {resume_text}
**Job Description:** {job_description}
**Candidate Profile Summary:** {profile_summary}
"""

job_stability_prompt = """
As an HR analytics expert, analyze the work history in this resume to determine if the candidate shows job-hopping tendencies.

### Task:
Review the resume and identify the candidate's job history, analyzing tenure at each position to evaluate stability.

### Output:
Return a valid JSON object ONLY with the following keys:
* `"IsStable"` (boolean): true if candidate shows good job stability, false if there are job-hopping concerns
* `"AverageJobTenure"` (string): estimated average time spent at each position (e.g., "2.5 years")
* `"JobCount"` (number): total number of positions held
* `"StabilityScore"` (number): 0-100 score indicating job stability (higher is better)
* `"ReasoningExplanation"` (string): brief explanation of the stability assessment
* `"RiskLevel"` (string): "Low", "Medium", or "High" risk of leaving quickly

Do NOT include any additional text, explanations, or formatting outside the JSON object.

---
**Resume:** {resume_text}
"""

# Add career progression prompt template after other prompt templates
career_prompt = """
You are an expert HR analyst. Analyze the candidate's career progression from their resume.
Focus on identifying career growth, job transitions, and progression patterns.

Provide your analysis in the following JSON format ONLY:
{
    "progression_score": <number 0-100 representing overall career growth>,
    "key_observations": [
        "<clear, specific observation about career path>",
        "<another observation>"
    ],
    "career_path": [
        {
            "title": "<job title>",
            "company": "<company name>",
            "duration": "<time period>",
            "level": "<Entry/Mid/Senior/Lead/Manager>",
            "progression": "<Promotion/Lateral/Step Back>"
        }
    ],
    "red_flags": [
        "<potential concern>",
        "<another concern if any>"
    ],
    "reasoning": "<detailed explanation of career progression analysis>"
}

Guidelines:
- progression_score should reflect overall career growth trajectory (0-100)
- key_observations should highlight important career moves and patterns
- career_path should be chronological, newest first
- red_flags should identify potential concerns for hiring
- reasoning should explain the overall career progression analysis

Resume text:
{resume_text}
"""

# Initialize Gemini model
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash')

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
asgi_app = WsgiToAsgi(app)

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize NLTK
nltk.download("punkt")


# Initialize Groq LLM
llm = ChatGroq(
    groq_api_key=GROQ_API_KEY,
    # model_name="mixtral-8x7b-32768",  # This generates long text,  max_tokens=4096
    model_name="qwen-2.5-32b",  
    temperature=0.377,
    max_tokens=4096,   #4096
    top_p=0.95,
    presence_penalty=0.1,
    frequency_penalty=0.1
)

# Initialize Pinecone
from pinecone import Pinecone, ServerlessSpec

# Initialize Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)
index_name = PINECONE_INDEX_NAME
if index_name not in pc.list_indexes().names():
    pc.create_index(
        name=index_name,
        dimension=384,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-west-2")
    )
index = pc.Index(index_name)

# Initialize embeddings
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# Initialize vector store
vectorstore = PineconeVectorStore(
    index=index,
    embedding=embeddings,
    text_key="text"
)

# Initialize database
DATABASE_NAME = 'combined_db.db'

def init_db():
    """Initialize database with all required tables"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # Create evaluations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resume_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            job_title TEXT NOT NULL,
            job_description TEXT,
            match_percentage REAL NOT NULL,
            match_factors TEXT,
            profile_summary TEXT,
            missing_keywords TEXT,
            job_stability TEXT,
            career_progression TEXT,
            technical_questions TEXT,
            nontechnical_questions TEXT,
            behavioral_questions TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create qa_history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS qa_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            retrieved_docs TEXT,
            final_answer TEXT,
            feedback TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create qa_feedback table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS qa_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            rating INTEGER,
            feedback TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES qa_history (id)
        )
    ''')
    
    # Create feedback table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id INTEGER,
            rating INTEGER,
            comments TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (evaluation_id) REFERENCES evaluations (id)
        )
    ''')
    
    # Create interview_questions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS interview_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id INTEGER,
            technical_questions TEXT,
            nontechnical_questions TEXT,
            behavioral_questions TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (evaluation_id) REFERENCES evaluations (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database at startup
init_db()

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_gemini_response(input_prompt):
    """Get response from Gemini model and clean it up."""
    try:
        response = model.generate_content(input_prompt)
        response_text = response.text.strip()
        
        # Remove markdown code block markers if present
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
            
        # Clean up any extra whitespace and newlines
        response_text = response_text.strip()
        
        # Try to parse as JSON to validate
        try:
            parsed_json = json.loads(response_text)
            return json.dumps(parsed_json)  # Return properly formatted JSON string
        except json.JSONDecodeError:
            # If not valid JSON, try to extract JSON using regex
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                try:
                    parsed_json = json.loads(match.group(0))
                    return json.dumps(parsed_json)  # Return properly formatted JSON string
                except json.JSONDecodeError:
                    raise ValueError("Invalid JSON structure in response")
            else:
                raise ValueError("No valid JSON found in response")
                
    except Exception as e:
        logging.error(f"Error in get_gemini_response: {str(e)}")
        return json.dumps({})  # Return valid empty JSON object as fallback

def extract_text_from_file(file_path):
    try:
        ext = file_path.rsplit('.', 1)[1].lower()
        if ext == 'pdf':
            try:
                with pdfplumber.open(file_path) as pdf:
                    text = ""
                    for page in pdf.pages:
                        text += page.extract_text() or ""
                return text
            except ModuleNotFoundError as e:
                if "PyCryptodome" in str(e) or "Crypto" in str(e):
                    return None, "PyCryptodome is required for encrypted PDFs. Please install it with 'pip install pycryptodome'."
                raise
        elif ext == 'docx':
            doc = Document(file_path)
            text = ""
            for para in doc.paragraphs:
                text += para.text + "\n"
            return text
        elif ext == 'doc':
            return None, "Support for .doc files is limited. Please convert to .docx or PDF."
        else:
            return None, "Unsupported file format."
    except Exception as e:
        logging.error(f"File extraction error: {str(e)}")
        return None, str(e)

def hybrid_search(query, k=5):
    """Perform hybrid search using BM25 and vector similarity."""
    try:
        # Get vector search results
        vector_results = vectorstore.similarity_search(query, k=k)
        
        # Get BM25 results
        bm25_results = []
        if os.path.exists(POLICIES_FOLDER):
            for filename in os.listdir(POLICIES_FOLDER):
                if filename.endswith(('.txt', '.md')):
                    with open(os.path.join(POLICIES_FOLDER, filename), 'r', encoding='utf-8') as f:
                        text = f.read()
                        sentences = sent_tokenize(text)
                        bm25_results.extend(sentences)
        
        # Combine and deduplicate results
        combined_results = []
        seen_texts = set()
        
        # Add vector search results
        for doc in vector_results:
            if doc.page_content not in seen_texts:
                combined_results.append(doc.page_content)
                seen_texts.add(doc.page_content)
        
        # Add BM25 results
        for sentence in bm25_results:
            if sentence not in seen_texts:
                combined_results.append(sentence)
                seen_texts.add(sentence)
        
        # Join results with newlines
        return "\n".join(combined_results)
    
    except Exception as e:
        logging.error(f"Error in hybrid_search: {e}")
        return ""

def save_evaluation(eval_id, filename, job_title, rank_score, missing_keywords, profile_summary, match_factors, job_stability, additional_info=None):
    try:
        conn = sqlite3.connect('combined_db.db')
        cursor = conn.cursor()
        
        # Convert data to JSON strings if they're not already
        missing_keywords_json = json.dumps(missing_keywords) if not isinstance(missing_keywords, str) else missing_keywords
        match_factors_json = json.dumps(match_factors) if not isinstance(match_factors, str) else match_factors
        job_stability_json = json.dumps(job_stability) if not isinstance(job_stability, str) else job_stability
        
        # Convert rank_score to integer if it's a string
        rank_score_int = int(rank_score) if isinstance(rank_score, str) else rank_score
        
        # Ensure all values are strings except rank_score_int and eval_id
        filename_str = str(filename)
        job_title_str = str(job_title)
        profile_summary_str = str(profile_summary)
        
        # Convert additional_info to JSON string if it's a dict or list
        if isinstance(additional_info, (dict, list)):
            additional_info_str = json.dumps(additional_info)
        else:
            additional_info_str = str(additional_info) if additional_info is not None else ""
        
        # Extract career progression from additional_info
        career_progression = additional_info.get('career_progression', {}) if isinstance(additional_info, dict) else {}
        career_progression_json = json.dumps(career_progression)
        
        cursor.execute(
            """
            INSERT INTO evaluations (
                resume_path, filename, job_title, match_percentage, 
                match_factors, profile_summary, missing_keywords, 
                job_stability, career_progression, technical_questions,
                nontechnical_questions, behavioral_questions, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filename_str, filename_str, job_title_str, rank_score_int, 
                match_factors_json, profile_summary_str, missing_keywords_json, 
                job_stability_json, career_progression_json, None, None, None, datetime.now()
            )
        )
        conn.commit()
        conn.close()
        logging.debug(f"Evaluation saved successfully: {eval_id}")
        return True
    except Exception as e:
        logging.error(f"Database error in save_evaluation: {str(e)}")
        return False

def save_feedback(evaluation_id, rating, comments):
    try:
        conn = sqlite3.connect('combined_db.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO feedback (evaluation_id, rating, comments, timestamp) VALUES (?, ?, ?, ?)",
            (evaluation_id, rating, comments, datetime.now())
        )
        logging.debug(f"Feedback inserted: evaluation_id={evaluation_id}, rating={rating}, comments={comments}")
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        logging.error(f"Database error in save_feedback: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in save_feedback: {str(e)}")
        return False

def save_interview_questions(evaluation_id, technical_questions, nontechnical_questions, behavioral_questions):
    """Save interview questions to database"""
    try:
        conn = sqlite3.connect('combined_db.db')
        cursor = conn.cursor()
        
        technical_json = json.dumps(technical_questions) if not isinstance(technical_questions, str) else technical_questions
        nontechnical_json = json.dumps(nontechnical_questions) if not isinstance(nontechnical_questions, str) else nontechnical_questions
        behavioral_json = json.dumps(behavioral_questions) if not isinstance(behavioral_questions, str) else behavioral_questions
        
        cursor.execute(
            "INSERT INTO interview_questions (evaluation_id, technical_questions, nontechnical_questions, behavioral_questions, timestamp) VALUES (?, ?, ?, ?, ?)",
            (evaluation_id, technical_json, nontechnical_json, behavioral_json, datetime.now())
        )
        conn.commit()
        conn.close()
        logging.debug(f"Interview questions saved successfully for: {evaluation_id}")
        return True
    except Exception as e:
        logging.error(f"Database error in save_interview_questions: {str(e)}")
        return False

# Add these constants near the top with other constants
BOT_INFO = {
    "name": "PeopleBot",
    "creator": "PeopleLogic",
    "responsibility": "Help recruiters in HR policies,benefits & events and with generic questions",
    "capabilities": "Help recruiters in HR policies benefits & events & with generic questions"
}

GREETINGS = ["hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening"]
IDENTITY_QUESTIONS = [
    "who are you",
    "what are you",
    "who built you",
    "who created you",
    "what can you do",
    "what do you do",
    "what is your name",
    "tell me about yourself"
]

def handle_special_queries(question):
    """Handle greetings and identity-related questions."""
    question_lower = question.lower().strip("?!. ")
    
    # Handle greetings
    if question_lower in GREETINGS:
        return f"Hello! I'm {BOT_INFO['name']}, your HR assistant. How can I help you today?"
    
    # Handle identity questions
    if any(q in question_lower for q in IDENTITY_QUESTIONS):
        if "who" in question_lower or "what is your name" in question_lower:
            return f"I'm {BOT_INFO['name']}, an AI assistant {BOT_INFO['creator']}. {BOT_INFO['responsibility']}"
        elif "created" in question_lower or "built" in question_lower:
            return f"I was created by {BOT_INFO['creator']} to {BOT_INFO['responsibility']}"
        elif "can you do" in question_lower or "do you do" in question_lower:
            return f"I can {BOT_INFO['capabilities']}"
        else:
            return f"I'm {BOT_INFO['name']}, an AI assistant created by {BOT_INFO['creator']}. {BOT_INFO['capabilities']}"
    
    return None

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/hr-assistant')
def hr_assistant():
    return render_template('index1.html')

@app.route('/resume-evaluator')
def resume_evaluator():
    return render_template('index2.html')

@app.route('/history')
def history():
    conn = sqlite3.connect('combined_db.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT 
                e.id, 
                e.filename, 
                e.job_title, 
                e.match_percentage, 
                e.missing_keywords, 
                e.profile_summary, 
                e.job_stability,
                e.career_progression,
                e.timestamp,
                iq.technical_questions,
                iq.nontechnical_questions
            FROM evaluations e
            LEFT JOIN interview_questions iq ON e.id = iq.evaluation_id
            ORDER BY e.timestamp DESC
        ''')
        
        evaluations = []
        for row in cursor.fetchall():
            try:
                # Helper function for safe JSON parsing
                def safe_json_loads(data, default):
                    if not data:
                        logging.info(f"Empty data for field, using default: {default}")
                        return default
                    try:
                        if isinstance(data, str):
                            return json.loads(data)
                        return data
                    except json.JSONDecodeError as e:
                        logging.error(f"JSON parsing error for evaluation {row[0]}: {str(e)} - Data: {data}")
                        # Try to clean the string if it's malformed
                        if isinstance(data, str):
                            try:
                                # Remove any trailing commas, fix quotes
                                cleaned = re.sub(r',\s*}', '}', data)
                                cleaned = re.sub(r',\s*]', ']', cleaned)
                                return json.loads(cleaned)
                            except:
                                pass
                        return default
                
                # Parse JSON fields with robust error handling
                missing_keywords_raw = row[4]
                try:
                    if missing_keywords_raw:
                        missing_keywords = safe_json_loads(missing_keywords_raw, [])
                        # If it's a string that looks like a list but isn't parsed as one
                        if not isinstance(missing_keywords, list):
                            # Try to extract keywords from a string representation
                            if isinstance(missing_keywords, str):
                                # Remove brackets and split by commas
                                missing_keywords = [k.strip(' "\'') for k in missing_keywords.strip('[]').split(',')]
                            else:
                                missing_keywords = [str(missing_keywords)]
                    else:
                        missing_keywords = []
                except Exception as e:
                    logging.error(f"Error parsing missing_keywords for eval {row[0]}: {str(e)}")
                    missing_keywords = []
                
                # Log raw data for debugging
                logging.info(f"Raw job_stability data for eval {row[0]}: {row[6]}")
                logging.info(f"Raw career_progression data for eval {row[0]}: {row[7]}")
                
                # Handle job stability data
                job_stability_data = row[6]
                if job_stability_data:
                    try:
                        job_stability = safe_json_loads(job_stability_data, {})
                        # Ensure it has the expected structure
                        if not isinstance(job_stability, dict):
                            job_stability = {}
                    except Exception as e:
                        logging.error(f"Error processing job_stability for eval {row[0]}: {str(e)}")
                        job_stability = {}
                else:
                    job_stability = {}
                
                # Handle career progression data
                career_progression_data = row[7]
                if career_progression_data:
                    try:
                        career_progression = safe_json_loads(career_progression_data, {})
                        # Ensure it has the expected structure
                        if not isinstance(career_progression, dict):
                            career_progression = {}
                    except Exception as e:
                        logging.error(f"Error processing career_progression for eval {row[0]}: {str(e)}")
                        career_progression = {}
                else:
                    career_progression = {}
                
                # Handle questions
                technical_questions = safe_json_loads(row[9], [])
                nontechnical_questions = safe_json_loads(row[10], [])
                
                # Ensure profile_summary is a valid string
                profile_summary = str(row[5]) if row[5] is not None else "No summary available"
                
                # Create a default structure for job_stability if empty
                if not job_stability:
                    job_stability = {
                        "StabilityScore": 0,
                        "AverageJobTenure": "N/A",
                        "JobCount": 0,
                        "RiskLevel": "N/A",
                        "ReasoningExplanation": "No job stability data available."
                    }
                
                # Create a default structure for career_progression if empty
                if not career_progression:
                    career_progression = {
                        "progression_score": 0,
                        "key_observations": [],
                        "career_path": [],
                        "red_flags": [],
                        "reasoning": "No career progression data available."
                    }
                
                # Ensure all data is properly serialized for the template
                # This is critical to avoid issues with the template's tojson filter
                try:
                    # Test serialization to catch any issues
                    json.dumps(job_stability)
                    json.dumps(career_progression)
                    json.dumps(technical_questions)
                    json.dumps(nontechnical_questions)
                except (TypeError, ValueError) as e:
                    logging.error(f"Serialization error for evaluation {row[0]}: {str(e)}")
                    # If there's an error, convert to string representation
                    if not isinstance(job_stability, dict):
                        job_stability = {"error": "Invalid data structure", "message": str(job_stability)}
                    if not isinstance(career_progression, dict):
                        career_progression = {"error": "Invalid data structure", "message": str(career_progression)}
                    if not isinstance(technical_questions, list):
                        technical_questions = ["Error loading technical questions"]
                    if not isinstance(nontechnical_questions, list):
                        nontechnical_questions = ["Error loading non-technical questions"]
                
                evaluation = {
                    'id': row[0],
                    'filename': row[1],
                    'job_title': row[2],
                    'match_percentage': row[3],
                    'missing_keywords': missing_keywords,
                    'profile_summary': profile_summary,
                    'job_stability': job_stability,
                    'career_progression': career_progression,
                    'timestamp': row[8],
                    'technical_questions': technical_questions,
                    'nontechnical_questions': nontechnical_questions
                }
                evaluations.append(evaluation)
                
                # Log the processed data for debugging
                logging.info(f"Processed evaluation {row[0]}: job_stability={job_stability}, career_progression={career_progression}")
                
            except Exception as e:
                logging.error(f"Error processing row for evaluation {row[0]}: {str(e)}")
                continue
            
        return render_template('history.html', evaluations=evaluations)
    
    except Exception as e:
        logging.error(f"Error in history route: {str(e)}")
        return render_template('history.html', evaluations=[], error="Failed to load evaluations")
    
    finally:
        conn.close()

@app.route('/feedback_history')
def feedback_history():
    conn = sqlite3.connect('combined_db.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.evaluation_id, e.filename, e.job_title, f.rating, f.comments, f.timestamp
        FROM feedback f
        JOIN evaluations e ON f.evaluation_id = e.id
        ORDER BY f.timestamp DESC
    """)
    feedback_entries = []
    for row in cursor.fetchall():
        feedback_entries.append({
            'evaluation_id': row[0],
            'filename': row[1],
            'job_title': row[2],
            'rating': row[3],
            'comments': row[4],
            'submitted_at': row[5]  # Keep the key as 'submitted_at' for frontend compatibility
        })
    conn.close()
    return render_template('feedback_history.html', feedback_entries=feedback_entries)

# HR Assistant Routes
@app.route('/api/ask', methods=['POST'])
def ask_question():
    try:
        data = request.get_json()
        question = data.get('question')
        online_mode = data.get('online_mode', False)

        if not question:
            return jsonify({'error': 'No question provided'}), 400

        def generate():
            complete_response = []  # Store complete response
            try:
                # Check for special queries first
                special_response = handle_special_queries(question)
                if special_response:
                    complete_response.append(special_response)
                    yield special_response
                    return

                # Expand acronyms in the question
                expanded_question = expand_acronyms(question)

                if online_mode:
                    # Enhanced detailed prompt for online mode
                    detailed_prompt = f"""As an expert HR Assistant, provide a comprehensive and detailed answer to the following question about HR policies, benefits, or procedures. Your response should be thorough and well-structured.

                    Question: {expanded_question}

                    Please provide a detailed response that includes:
                    1. Overview and Introduction
                    2. Main Policy Details or Procedures
                    3. Important Rules and Guidelines
                    4. Exceptions or Special Cases
                    5. Implementation Details
                    6. Related Policies or Cross-references
                    7. Examples or Scenarios (if applicable)
                    8. Best Practices and Recommendations
                    9. Important Considerations
                    10. Additional Resources or References

                    Format your response with clear sections and bullet points where appropriate.
                    Ensure all relevant details are covered comprehensively."""
                    
                    response = model.generate_content(detailed_prompt, stream=True)
                    for chunk in response:
                        if chunk.text:
                            complete_response.append(chunk.text)
                            yield chunk.text
                else:
                    # Enhanced RAG with more context and detailed prompt
                    docs = vectorstore.similarity_search(expanded_question, k=8)  # Increased from 5 to 8 for more context
                    context = "\n\n".join([doc.page_content for doc in docs])
                    
                    prompt = f"""As an expert HR Assistant, provide a comprehensive and detailed answer using the provided context. Your response should be thorough and well-structured.

                    Context:
                    {context}

                    Question: {expanded_question}

                    Please provide a detailed response that includes:
                    1. Direct Answer from Policy Documents
                    2. Detailed Policy Information
                    3. Rules and Guidelines
                    4. Procedures and Steps
                    5. Important Exceptions
                    6. Related Information
                    7. Examples or Use Cases
                    8. Best Practices
                    9. Additional Considerations
                    10. Cross-references to Other Policies

                    Format your response with clear sections and bullet points where appropriate.
                    If certain information is not available in the context, acknowledge this and provide the information that is available."""
                    
                    response = llm.stream(prompt)
                    for chunk in response:
                        if chunk.content:
                            complete_response.append(chunk.content)
                            yield chunk.content

                # Store the complete Q&A in history after streaming is done
                final_answer = "".join(complete_response)
                conn = sqlite3.connect('combined_db.db')
                c = conn.cursor()
                c.execute('''INSERT INTO qa_history (question, retrieved_docs, final_answer)
                            VALUES (?, ?, ?)''', (question, context if not online_mode else None, final_answer))
                conn.commit()
                conn.close()

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                yield error_msg
                # Store error in database
                conn = sqlite3.connect('combined_db.db')
                c = conn.cursor()
                c.execute('''INSERT INTO qa_history (question, final_answer)
                            VALUES (?, ?)''', (question, error_msg))
                conn.commit()
                conn.close()

        return Response(stream_with_context(generate()), mimetype='text/plain')

    except Exception as e:
        print(f"Error in ask_question: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route("/api/update_index", methods=["POST"])
def update_index_api():
    """Manually refresh the Pinecone & BM25 index."""
    try:
        # Rebuild BM25 index
        build_bm25_index(POLICIES_FOLDER)
        
        # Repopulate Pinecone
        populate_pinecone_index()
        
        return jsonify({"message": "Indexes updated successfully"}), 200
    except Exception as e:
        logging.error(f"❌ Index Update Error: {e}", exc_info=True)
        return jsonify({"error": "Failed to update indexes"}), 500

# Resume Evaluator Routes
async def async_gemini_generate(prompt):
    """Async wrapper for Gemini generation with improved JSON handling"""
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Remove any JSON formatting artifacts
        response_text = response_text.replace('\n', ' ')
        response_text = re.sub(r'\s+', ' ', response_text)
        
        # Remove markdown code block markers if present
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)
        
        # Try to parse as JSON
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON using regex
            json_match = re.search(r'\{.*\}', response_text)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    logging.error(f"Failed to parse extracted JSON: {json_match.group(0)}")
                    return get_default_career_analysis()
            else:
                logging.error(f"No JSON found in response: {response_text}")
                return get_default_career_analysis()
                
    except Exception as e:
        logging.error(f"Gemini generation error: {str(e)}")
        return get_default_career_analysis()

async def async_analyze_stability(resume_text):
    """Async job stability analysis"""
    try:
        stability_prompt = job_stability_prompt.format(resume_text=resume_text)
        response = await async_gemini_generate(stability_prompt)
        
        if not response:
            raise ValueError("Failed to get stability analysis")
            
        # Ensure all required fields exist
        default_data = {
            "IsStable": True,
            "AverageJobTenure": "Unknown",
            "JobCount": 0,
            "StabilityScore": 0,
            "ReasoningExplanation": "Could not analyze job stability",
            "RiskLevel": "Unknown"
        }
        
        # Merge response with defaults
        for key, default_value in default_data.items():
            if key not in response:
                response[key] = default_value
                
        return response
        
    except Exception as e:
        logging.error(f"Error in async_analyze_stability: {str(e)}")
        return {
            "IsStable": True,
            "AverageJobTenure": "Unknown",
            "JobCount": 0,
            "StabilityScore": 0,
            "ReasoningExplanation": "Could not analyze job stability",
            "RiskLevel": "Unknown"
        }

async def async_generate_questions(resume_text, job_description, profile_summary):
    """Async interview questions generation"""
    try:
        questions_prompt = interview_questions_prompt.format(
            resume_text=resume_text,
            job_description=job_description,
            profile_summary=profile_summary
        )
        response = await async_gemini_generate(questions_prompt)
        
        if not response:
            raise ValueError("Failed to generate interview questions")
            
        # Ensure we have the required fields with proper defaults
        default_data = {
            "TechnicalQuestions": [],
            "NonTechnicalQuestions": []
        }
        
        # Merge response with defaults
        for key, default_value in default_data.items():
            if key not in response:
                response[key] = default_value
            elif not isinstance(response[key], list):
                response[key] = [str(response[key])] if response[key] else []
                
        return response
        
    except Exception as e:
        logging.error(f"Error in async_generate_questions: {str(e)}")
        return {
            "TechnicalQuestions": [],
            "NonTechnicalQuestions": []
        }

@app.route('/evaluate', methods=['POST'])
async def evaluate_resume():
    try:
        if 'resume' not in request.files:
            return jsonify({'error': 'No resume file provided'}), 400
        
        file = request.files['resume']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400

        job_title = request.form.get('job_title')
        job_description = request.form.get('job_description')

        if not job_title or not job_description:
            return jsonify({'error': 'Missing job title or description'}), 400

        # Save uploaded file
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Extract text from resume
        resume_text = extract_text_from_file(file_path)
        if resume_text is None:
            return jsonify({'error': 'Failed to extract text from file'}), 500

        # Generate evaluation using Gemini with optimized parameters
        formatted_prompt = input_prompt_template.format(resume_text=resume_text, job_description=job_description)
        
        try:
            # Run all analyses concurrently using asyncio.gather
            main_response, stability_data, career_data = await asyncio.gather(
                async_gemini_generate(formatted_prompt),
                async_analyze_stability(resume_text),
                analyze_career_progression(resume_text)  # Now properly awaited
            )
            
            if not main_response:
                raise ValueError("Failed to get main evaluation response")
                
            if not career_data:
                career_data = {
                    "progression_score": 50,
                    "key_observations": ["Failed to analyze career progression"],
                    "career_path": [],
                    "red_flags": ["Analysis error"],
                    "reasoning": "Failed to process career data"
                }
                
        except Exception as e:
            logging.error(f"Error during concurrent analysis: {str(e)}")
            return jsonify({'error': 'Failed to analyze resume'}), 500
        
        # Extract values from main response
        match_percentage_str = main_response.get("JD Match", "0%")
        match_percentage = int(match_percentage_str.strip('%'))
        missing_keywords = main_response.get("MissingKeywords", [])
        profile_summary = main_response.get("Profile Summary", "No summary provided.")
        extra_info = main_response.get("Extra Info", "")
        match_factors = main_response.get("Match Factors", {})

        # Prepare additional information
        additional_info = {
            "job_stability": stability_data,
            "career_progression": career_data,
            "reasoning": main_response.get("Reasoning", "")
        }

        # Generate unique ID for evaluation
        eval_id = str(uuid.uuid4())

        # Save evaluation to database with additional info
        if save_evaluation(eval_id, filename, job_title, match_percentage, missing_keywords, profile_summary, match_factors, stability_data, additional_info):
            # Generate interview questions asynchronously
            questions_data = await async_generate_questions(resume_text, job_description, profile_summary)
            
            technical_questions = questions_data.get("TechnicalQuestions", [])
            nontechnical_questions = questions_data.get("NonTechnicalQuestions", [])
            behavioral_questions = QUICK_CHECKS

            # Save interview questions with proper JSON encoding
            if save_interview_questions(eval_id, 
                                     json.dumps(technical_questions), 
                                     json.dumps(nontechnical_questions), 
                                     json.dumps(behavioral_questions)):
                return jsonify({
                    'id': eval_id,
                    'match_percentage': match_percentage,
                    'match_percentage_str': match_percentage_str,
                    'missing_keywords': missing_keywords,
                    'profile_summary': profile_summary,
                    'extra_info': extra_info,
                    'match_factors': match_factors,
                    'job_stability': stability_data,
                    'career_progression': career_data,
                    'technical_questions': technical_questions,
                    'nontechnical_questions': nontechnical_questions,
                    'behavioral_questions': behavioral_questions
                })
            else:
                return jsonify({'error': 'Failed to save interview questions'}), 500
        else:
            return jsonify({'error': 'Failed to save evaluation'}), 500

    except Exception as e:
        logging.error(f"Error in evaluate_resume: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_interview_questions/<evaluation_id>', methods=['GET'])
def get_interview_questions(evaluation_id):
    """Get interview questions for a specific evaluation"""
    conn = None
    try:
        conn = sqlite3.connect('combined_db.db')
        cursor = conn.cursor()
        
        # First, get the evaluation details to regenerate questions if needed
        cursor.execute(
            """
            SELECT e.resume_path, e.job_title, e.job_description, e.profile_summary 
            FROM evaluations e 
            WHERE e.id = ?
            """,
            (evaluation_id,)
        )
        eval_result = cursor.fetchone()
        
        # Then get existing questions
        cursor.execute(
            "SELECT technical_questions, nontechnical_questions, behavioral_questions FROM interview_questions WHERE evaluation_id = ?",
            (evaluation_id,)
        )
        result = cursor.fetchone()
        
        if result:
            try:
                # Parse saved questions with proper error handling
                def parse_json_safely(json_str):
                    if not json_str:
                        return []
                    try:
                        data = json.loads(json_str)
                        if isinstance(data, list):
                            return data
                        elif isinstance(data, str):
                            try:
                                return json.loads(data)
                            except:
                                return [data]
                        else:
                            return [str(data)]
                    except json.JSONDecodeError:
                        try:
                            # Try to clean and parse the string
                            cleaned_str = json_str.strip('[]"\' ').replace('\\', '')
                            items = [item.strip('"\' ') for item in cleaned_str.split(',')]
                            return [item for item in items if item]
                        except:
                            return []

                technical_questions = parse_json_safely(result[0])
                nontechnical_questions = parse_json_safely(result[1])
                behavioral_questions = parse_json_safely(result[2])

                # If any question set is empty and we have evaluation data, regenerate
                if (not technical_questions or not nontechnical_questions) and eval_result:
                    resume_text = extract_text_from_file(eval_result[0])
                    if resume_text:
                        questions_data = asyncio.run(async_generate_questions(
                            resume_text,
                            eval_result[2],  # job_description
                            eval_result[3]   # profile_summary
                        ))
                        
                        if not technical_questions:
                            technical_questions = questions_data.get("TechnicalQuestions", [])
                        if not nontechnical_questions:
                            nontechnical_questions = questions_data.get("NonTechnicalQuestions", [])
                        if not behavioral_questions:
                            behavioral_questions = QUICK_CHECKS
                        
                        # Save regenerated questions
                        cursor.execute(
                            """
                            UPDATE interview_questions 
                            SET technical_questions = ?,
                                nontechnical_questions = ?,
                                behavioral_questions = ?
                            WHERE evaluation_id = ?
                            """,
                            (json.dumps(technical_questions), 
                             json.dumps(nontechnical_questions), 
                             json.dumps(behavioral_questions), 
                             evaluation_id)
                        )
                        conn.commit()

                return jsonify({
                    'technical_questions': technical_questions or ["No technical questions available"],
                    'nontechnical_questions': nontechnical_questions or ["No non-technical questions available"],
                    'behavioral_questions': behavioral_questions or QUICK_CHECKS
                })
                
            except Exception as e:
                logging.error(f"Error processing interview questions: {str(e)}")
                return jsonify({
                    'technical_questions': ["Error loading technical questions"],
                    'nontechnical_questions': ["Error loading non-technical questions"],
                    'behavioral_questions': QUICK_CHECKS
                })
        else:
            # No questions found, create new entry with default questions
            default_questions = {
                'technical_questions': ["No technical questions available"],
                'nontechnical_questions': ["No non-technical questions available"],
                'behavioral_questions': QUICK_CHECKS
            }
            
            cursor.execute(
                """
                INSERT INTO interview_questions 
                (evaluation_id, technical_questions, nontechnical_questions, behavioral_questions) 
                VALUES (?, ?, ?, ?)
                """,
                (
                    evaluation_id,
                    json.dumps(default_questions['technical_questions']),
                    json.dumps(default_questions['nontechnical_questions']),
                    json.dumps(default_questions['behavioral_questions'])
                )
            )
            conn.commit()
            
            return jsonify(default_questions)

    except Exception as e:
        logging.error(f"Database error in get_interview_questions: {str(e)}")
        return jsonify({
            'technical_questions': ["Error loading technical questions"],
            'nontechnical_questions': ["Error loading non-technical questions"],
            'behavioral_questions': QUICK_CHECKS
        })
    finally:
        if conn:
            conn.close()

@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    """Handle feedback for both Q&A and resume evaluations."""
    try:
        data = request.get_json()
        logging.info(f"Received feedback data: {data}")
        
        if not data:
            logging.error("No feedback data received")
            return jsonify({'error': 'No feedback data provided'}), 400
            
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        
        try:
            # Check if this is Q&A feedback
            if 'question' in data:
                if 'rating' not in data:
                    return jsonify({'error': 'Missing rating'}), 400
                
                # Get question_id from qa_history
                cursor.execute("""
                    SELECT id FROM qa_history 
                    WHERE question = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """, (data['question'],))
                
                result = cursor.fetchone()
                if not result:
                    # If question not found, create a new entry
                    cursor.execute("""
                        INSERT INTO qa_history (question, final_answer)
                        VALUES (?, ?)
                    """, (data['question'], ''))
                    question_id = cursor.lastrowid
                else:
                    question_id = result[0]
                
                # Insert feedback
                cursor.execute("""
                    INSERT INTO qa_feedback (question_id, rating, feedback, timestamp)
                    VALUES (?, ?, ?, datetime('now'))
                """, (question_id, data['rating'], data.get('feedback', '')))
                
            else:
                # Handle resume evaluation feedback
                if 'evaluation_id' not in data or 'rating' not in data:
                    return jsonify({'error': 'Missing evaluation_id or rating'}), 400
                
                # Insert feedback into the feedback table
                cursor.execute("""
                    INSERT INTO feedback (evaluation_id, rating, comments, timestamp)
                    VALUES (?, ?, ?, datetime('now'))
                """, (data['evaluation_id'], data['rating'], data.get('comments', '')))
            
            conn.commit()
            return jsonify({'message': 'Feedback submitted successfully'})
            
        finally:
            conn.close()
            
    except sqlite3.Error as e:
        logging.error(f"Database error in submit_feedback: {str(e)}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        logging.error(f"Error in submit_feedback: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

# --- Document Processing ---
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=400,
    chunk_overlap=50
)

def process_pdf(pdf_path, documents, table_chunks):
    """Extract text and tables from a PDF file."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Extract and process text
                text = page.extract_text() or ""
                if text:
                    text_chunks = text_splitter.split_text(text)
                    documents.extend(text_chunks)
                
                # Extract and process tables
                tables = page.extract_tables()
                for table in tables:
                    if table and len(table) > 1:  # Ensure table has headers and data
                        df = pd.DataFrame(table[1:], columns=table[0])
                        table_markdown = df.to_markdown()
                        table_chunks.append(table_markdown)
    except Exception as e:
        logging.error(f"❌ Error processing PDF {pdf_path}: {e}")

def populate_pinecone_index():
    """Extract content from PDF documents and populate Pinecone index."""
    documents = []  # Text chunks
    table_chunks = []  # Table chunks
    
    # Process all PDF files in the policies folder
    for filename in os.listdir(POLICIES_FOLDER):
        if filename.endswith(".pdf"):
            pdf_path = os.path.join(POLICIES_FOLDER, filename)
            process_pdf(pdf_path, documents, table_chunks)
    
    # Combine all chunks and insert into Pinecone
    all_chunks = documents + table_chunks
    if all_chunks:
        LangchainPinecone.from_texts(all_chunks, embeddings, index_name=PINECONE_INDEX_NAME)
        logging.info(f"✅ Inserted {len(all_chunks)} chunks into Pinecone")
    else:
        logging.warning("⚠️ No content found to insert into Pinecone")

# --- BM25 Setup ---
bm25_index = None
bm25_corpus = None

def build_bm25_index(folder_path):
    """Builds BM25 index from policy documents."""
    global bm25_index, bm25_corpus
    
    all_texts = []
    table_chunks = []
    
    # Process all PDF files
    for filename in os.listdir(folder_path):
        if filename.endswith(".pdf"):
            pdf_path = os.path.join(folder_path, filename)
            process_pdf(pdf_path, all_texts, table_chunks)
    
    # Combine text and tables for indexing
    all_chunks = all_texts + table_chunks
    
    if all_chunks:
        # Tokenize for BM25
        bm25_corpus = [text.split() for text in all_chunks]
        bm25_index = BM25Okapi(bm25_corpus)
        logging.info(f"✅ BM25 index built with {len(bm25_corpus)} document chunks")
    else:
        logging.warning("⚠️ No content found for BM25 indexing")

def expand_query_with_llm(question, llm):
    """Expands user query using LLM to include synonyms but retains original meaning."""
    expansion_prompt = f"""
    Provide alternative phrasings and related terms for: '{question}', 
    ensuring the original word is always included. Include HR-specific terms if applicable.
    """
    try:
        expanded_query = llm.invoke(expansion_prompt).content
        logging.info(f"🔍 Query Expansion: {expanded_query}")
        return expanded_query
    except Exception as e:
        logging.error(f"❌ Query Expansion Failed: {e}")
        return question  # Fall back to the original question

def hybrid_search(question, llm, retriever):
    """Performs hybrid retrieval using BM25 and Pinecone vectors."""
    global bm25_index, bm25_corpus
    
    # Expand query
    expanded_query = expand_query_with_llm(question, llm)
    
    results = []
    
    # Step 1: BM25 Keyword Search
    if bm25_index and bm25_corpus:
        bm25_results = bm25_index.get_top_n(expanded_query.split(), bm25_corpus, n=5)
        bm25_texts = [" ".join(text) for text in bm25_results]
        results.extend(bm25_texts)
        logging.info(f"🔍 BM25 Retrieved {len(bm25_texts)} results")
    
    # Step 2: Vector Search
    pinecone_results = retriever.invoke(expanded_query)
    pinecone_texts = [doc.page_content for doc in pinecone_results]
    results.extend(pinecone_texts)
    
    # Prioritize table content (tables contain | character in markdown)
    table_texts = [text for text in results if "|" in text]
    non_table_texts = [text for text in results if "|" not in text]
    
    # Combine results: tables first, then other content
    combined_results = table_texts + non_table_texts
    
    # Remove duplicates while preserving order
    unique_results = []
    seen = set()
    for text in combined_results:
        # Use a hash of the text as a unique identifier
        text_hash = hash(text)
        if text_hash not in seen:
            seen.add(text_hash)
            unique_results.append(text)
    
    # Join and truncate to avoid token limits
    final_text = "\n\n".join(unique_results)[:5000]
    
    return final_text

def save_qa_to_db(question, retrieved_docs, final_answer, feedback=None):
    """Stores a Q&A pair in SQLite with optional feedback."""
    try:
        conn = sqlite3.connect('combined_db.db')
        cursor = conn.cursor()
        
        logging.info(f"Saving Q&A to DB - Question: {question[:50]}...")  # Debug log
        
        query = """
        INSERT INTO qa_history (question, retrieved_docs, final_answer, feedback) 
        VALUES (?, ?, ?, ?)
        """
        cursor.execute(query, (question, retrieved_docs, final_answer, feedback))
        conn.commit()
        
        question_id = cursor.lastrowid
        logging.info(f"✅ Q&A stored successfully with ID: {question_id}")
        return question_id
    except Exception as e:
        logging.error(f"❌ Error saving Q&A to DB: {e}", exc_info=True)
        return None
    finally:
        conn.close()

def setup_llm_chain():
    """Initialize the LLM and retrieval chain."""
    # Initialize LLM with optimized parameters
    llm = ChatGroq(
        model_name="mixtral-8x7b-32768",
        groq_api_key=GROQ_API_KEY,
        temperature=0.7,
        max_tokens=32768,
        top_p=0.95,
        presence_penalty=0.1,
        frequency_penalty=0.1,
        streaming=True
    )
    
    # Set up the vector store retriever
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    
    return llm, None, retriever  # Return None for qa_chain as we're not using it

def initialize_pinecone():
    """Initialize Pinecone and create index if it doesn't exist."""
    try:
        # Initialize Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        
        # Check if index exists
        if PINECONE_INDEX_NAME not in pc.list_indexes().names():
            # Create new index
            pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=384,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-west-2")
            )
            logging.info(f"✅ Created new Pinecone index: {PINECONE_INDEX_NAME}")
        else:
            logging.info(f"✅ Using existing Pinecone index: {PINECONE_INDEX_NAME}")
        
        # Get index
        index = pc.Index(PINECONE_INDEX_NAME)
        
        # Initialize embeddings
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Initialize vector store
        vectorstore = PineconeVectorStore(
            index=index,
            embedding=embeddings,
            text_key="text"
        )
        
        # Populate index if empty
        if index.describe_index_stats()['total_vector_count'] == 0:
            logging.info("🔄 Populating empty Pinecone index...")
            populate_pinecone_index()
        
        logging.info(f"✅ Pinecone initialized with {index.describe_index_stats()['total_vector_count']} vectors")
        return vectorstore
        
    except Exception as e:
        logging.error(f"❌ Error initializing Pinecone: {e}")
        raise

def expand_acronyms(question):
    """Expand HR-related acronyms in the question."""
    expanded_question = question.lower()
    for acronym, full_form in ACRONYM_MAP.items():
        expanded_question = expanded_question.replace(acronym.lower(), full_form.lower())
    return expanded_question

async def analyze_career_progression(resume_text):
    """Analyze career progression from resume text using Gemini."""
    try:
        formatted_prompt = f"""You are an expert HR analyst. Analyze this candidate's career progression.
Return ONLY a JSON object with the following structure, no other text:
{{
    "progression_score": <number 0-100>,
    "key_observations": [<list of string observations>],
    "career_path": [
        {{
            "title": "<job title>",
            "company": "<company name>",
            "duration": "<time period>",
            "level": "<Entry/Mid/Senior/Lead/Manager>",
            "progression": "<Promotion/Lateral/Step Back>"
        }}
    ],
    "red_flags": [<list of string concerns>],
    "reasoning": "<analysis explanation>"
}}

Resume text:
{resume_text}"""

        # Get response from Gemini
        response = await async_gemini_generate(formatted_prompt)
        
        # If response is already a dict (from async_gemini_generate)
        if isinstance(response, dict):
            parsed_response = response
        else:
            try:
                parsed_response = json.loads(response) if isinstance(response, str) else {}
            except json.JSONDecodeError:
                logging.error(f"Failed to parse response as JSON: {response}")
                return get_default_career_analysis()

        # Validate and clean the response data
        cleaned_data = {
            "progression_score": validate_progression_score(parsed_response.get("progression_score", 50)),
            "key_observations": validate_list(parsed_response.get("key_observations", [])) or ["No key observations found"],
            "career_path": validate_career_path(parsed_response.get("career_path", [])),
            "red_flags": validate_list(parsed_response.get("red_flags", [])) or ["No red flags identified"],
            "reasoning": str(parsed_response.get("reasoning", "No analysis provided")).strip()
        }

        # Ensure we have valid data
        if cleaned_data["progression_score"] == 50 and not cleaned_data["career_path"]:
            return get_default_career_analysis()
            
        return cleaned_data

    except Exception as e:
        logging.error(f"Career progression analysis error: {str(e)}")
        logging.error(f"Full traceback:", exc_info=True)
        return get_default_career_analysis()

def get_default_career_analysis():
    """Return default career analysis structure"""
    return {
        "progression_score": 50,
        "key_observations": ["Unable to analyze career progression"],
        "career_path": [],
        "red_flags": ["Analysis encountered technical issues"],
        "reasoning": "Analysis failed to complete"
    }

def validate_progression_score(score):
    """Validate and normalize progression score"""
    try:
        if isinstance(score, str):
            score = score.strip('%')
        score = float(score)
        return int(max(0, min(100, score)))
    except (ValueError, TypeError):
        return 50

def validate_list(items):
    """Validate and clean list items"""
    if not isinstance(items, list):
        return []
    return [str(item).strip() for item in items if item and str(item).strip()]

def validate_career_path(path):
    """Validate and clean career path entries"""
    if not isinstance(path, list):
        return []
    
    cleaned_path = []
    required_fields = ["title", "company", "duration", "level", "progression"]
    
    for entry in path:
        if not isinstance(entry, dict):
            continue
        
        cleaned_entry = {}
        for field in required_fields:
            cleaned_entry[field] = str(entry.get(field, "Not specified")).strip()
        cleaned_path.append(cleaned_entry)
    
    return cleaned_path

def update_db_schema():
    """Update database schema if needed"""
    conn = sqlite3.connect('combined_db.db')
    cursor = conn.cursor()
    
    # Add new columns if they don't exist
    try:
        cursor.execute('''
            ALTER TABLE evaluations 
            ADD COLUMN job_stability TEXT;
        ''')
    except sqlite3.OperationalError:
        pass  # Column already exists
        
    try:
        cursor.execute('''
            ALTER TABLE evaluations 
            ADD COLUMN career_progression TEXT;
        ''')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    conn.commit()
    conn.close()

@app.route('/api/evaluation/<evaluation_id>', methods=['GET'])
def get_evaluation_details(evaluation_id):
    """API endpoint to get evaluation details by ID"""
    conn = None
    try:
        logging.info(f"Fetching evaluation details for ID: {evaluation_id}")
        conn = sqlite3.connect('combined_db.db')
        cursor = conn.cursor()
        
        # Helper function for parsing JSON safely
        def parse_json_safely(json_str):
            if not json_str:
                logging.info("Empty JSON string, returning empty list")
                return []
            try:
                data = json.loads(json_str)
                if isinstance(data, list):
                    logging.info(f"Successfully parsed list with {len(data)} items")
                    return data
                elif isinstance(data, str):
                    try:
                        parsed_data = json.loads(data)
                        logging.info(f"Successfully parsed nested JSON string")
                        return parsed_data
                    except:
                        logging.info(f"Failed to parse nested JSON, treating as single item")
                        return [data]
                else:
                    logging.info(f"Non-list data type: {type(data)}, converting to string")
                    return [str(data)]
            except json.JSONDecodeError as e:
                logging.warning(f"JSON decode error: {str(e)}, attempting cleanup")
                try:
                    # Try to clean and parse the string
                    cleaned_str = json_str.strip('[]"\' ').replace('\\', '')
                    items = [item.strip('"\' ') for item in cleaned_str.split(',')]
                    result = [item for item in items if item]
                    logging.info(f"Cleanup successful, extracted {len(result)} items")
                    return result
                except Exception as e2:
                    logging.error(f"Cleanup failed: {str(e2)}")
                    return []
        
        # Get evaluation details first to get job title for default questions
        cursor.execute('''
            SELECT 
                e.id, 
                e.filename, 
                e.job_title, 
                e.match_percentage, 
                e.profile_summary, 
                e.job_stability,
                e.career_progression,
                e.timestamp,
                e.missing_keywords,
                e.behavioral_questions,
                e.technical_questions,
                e.nontechnical_questions
            FROM evaluations e
            WHERE e.id = ?
        ''', (evaluation_id,))
        
        row = cursor.fetchone()
        if not row:
            logging.warning(f"No evaluation found with ID: {evaluation_id}")
            return jsonify({'error': 'Evaluation not found'}), 404
        
        logging.info(f"Found evaluation with ID: {row[0]}, filename: {row[1]}")
        job_title = row[2]
        
        # Parse JSON fields
        try:
            job_stability = json.loads(row[5]) if row[5] else {}
            logging.info(f"Parsed job_stability: {type(job_stability)}")
        except Exception as e:
            logging.error(f"Error parsing job_stability: {str(e)}")
            job_stability = {}
            
        try:
            career_progression = json.loads(row[6]) if row[6] else {}
            logging.info(f"Parsed career_progression: {type(career_progression)}")
        except Exception as e:
            logging.error(f"Error parsing career_progression: {str(e)}")
            career_progression = {}
        
        # Parse missing keywords with special handling
        try:
            missing_keywords_raw = row[8]
            if missing_keywords_raw:
                try:
                    missing_keywords = json.loads(missing_keywords_raw)
                    logging.info(f"Parsed missing_keywords: {type(missing_keywords)}")
                    # If it's not a list, try to convert it
                    if not isinstance(missing_keywords, list):
                        if isinstance(missing_keywords, str):
                            # Remove brackets and split by commas
                            missing_keywords = [k.strip(' "\'') for k in missing_keywords.strip('[]').split(',')]
                        else:
                            missing_keywords = [str(missing_keywords)]
                except Exception as e:
                    logging.error(f"Error parsing missing_keywords JSON: {str(e)}")
                    # If JSON parsing fails, try to extract from string
                    if isinstance(missing_keywords_raw, str):
                        # Check if it looks like a list
                        if missing_keywords_raw.startswith('[') and missing_keywords_raw.endswith(']'):
                            # Remove brackets and split by commas
                            missing_keywords = [k.strip(' "\'') for k in missing_keywords_raw.strip('[]').split(',')]
                        else:
                            missing_keywords = [missing_keywords_raw]
                    else:
                        missing_keywords = []
            else:
                missing_keywords = []
        except Exception as e:
            logging.error(f"Error processing missing_keywords: {str(e)}")
            missing_keywords = []
        
        # Initialize question variables
        technical_questions = []
        nontechnical_questions = []
        behavioral_questions = []
        
        # Try to get behavioral questions from evaluations
        try:
            behavioral_questions_raw = row[9]
            if behavioral_questions_raw:
                behavioral_questions = parse_json_safely(behavioral_questions_raw)
                logging.info(f"Parsed behavioral_questions from evaluations: {len(behavioral_questions)} questions")
        except Exception as e:
            logging.error(f"Error parsing behavioral_questions from evaluations: {str(e)}")
        
        # Try to get technical questions from evaluations
        try:
            if row[10]:
                technical_questions = parse_json_safely(row[10])
                logging.info(f"Parsed technical_questions from evaluations: {len(technical_questions)} questions")
        except Exception as e:
            logging.error(f"Error parsing technical_questions from evaluations: {str(e)}")
        
        # Try to get non-technical questions from evaluations
        try:
            if row[11]:
                nontechnical_questions = parse_json_safely(row[11])
                logging.info(f"Parsed nontechnical_questions from evaluations: {len(nontechnical_questions)} questions")
        except Exception as e:
            logging.error(f"Error parsing nontechnical_questions from evaluations: {str(e)}")
        
        # Now try to get interview questions from interview_questions table
        # First try with the numeric ID
        cursor.execute(
            "SELECT technical_questions, nontechnical_questions, behavioral_questions FROM interview_questions WHERE evaluation_id = ?",
            (evaluation_id,)
        )
        iq_result = cursor.fetchone()
        
        if not iq_result:
            logging.info(f"No interview questions found with numeric ID, trying string ID")
            # If no results, try with the string representation of the ID
            cursor.execute(
                "SELECT technical_questions, nontechnical_questions, behavioral_questions FROM interview_questions WHERE evaluation_id = ?",
                (str(evaluation_id),)
            )
            iq_result = cursor.fetchone()
        
        if iq_result:
            logging.info(f"Found interview questions in interview_questions table, parsing")
            # Only update if we don't already have questions
            if not technical_questions:
                technical_questions = parse_json_safely(iq_result[0])
                logging.info(f"Parsed technical_questions from interview_questions: {len(technical_questions)} questions")
            
            if not nontechnical_questions:
                nontechnical_questions = parse_json_safely(iq_result[1])
                logging.info(f"Parsed nontechnical_questions from interview_questions: {len(nontechnical_questions)} questions")
            
            if not behavioral_questions:
                behavioral_questions = parse_json_safely(iq_result[2])
                logging.info(f"Parsed behavioral_questions from interview_questions: {len(behavioral_questions)} questions")
        
        # If still no behavioral questions, use default QUICK_CHECKS
        if not behavioral_questions:
            logging.info("No behavioral questions found, using QUICK_CHECKS")
            behavioral_questions = QUICK_CHECKS
        
        # If still no technical or non-technical questions, generate defaults based on job title
        if not technical_questions or not nontechnical_questions:
            logging.info(f"Generating default questions for job title: {job_title}")
            default_technical, default_nontechnical = get_default_interview_questions(job_title)
            
            if not technical_questions:
                technical_questions = default_technical
                logging.info(f"Using default technical questions: {len(technical_questions)} questions")
            
            if not nontechnical_questions:
                nontechnical_questions = default_nontechnical
                logging.info(f"Using default non-technical questions: {len(nontechnical_questions)} questions")
        
        # Create response
        response = {
            'id': row[0],
            'filename': row[1],
            'job_title': row[2],
            'match_percentage': row[3],
            'profile_summary': row[4] or "No summary available",
            'job_stability': job_stability,
            'career_progression': career_progression,
            'timestamp': row[7],
            'missing_keywords': missing_keywords,
            'technical_questions': technical_questions,
            'nontechnical_questions': nontechnical_questions,
            'behavioral_questions': behavioral_questions
        }
        
        logging.info(f"Returning response with {len(technical_questions)} technical questions, {len(nontechnical_questions)} non-technical questions, {len(behavioral_questions)} behavioral questions")
        return jsonify(response)
    
    except Exception as e:
        logging.error(f"Error fetching evaluation details: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
    finally:
        if conn:
            conn.close()

@app.route('/api/generate_questions/<evaluation_id>', methods=['POST'])
async def generate_questions_api(evaluation_id):
    """API endpoint to generate interview questions for an evaluation"""
    conn = None
    try:
        logging.info(f"Generating questions for evaluation ID: {evaluation_id}")
        conn = sqlite3.connect('combined_db.db')
        cursor = conn.cursor()
        
        # Get evaluation details
        cursor.execute(
            """
            SELECT resume_path, job_title, job_description, profile_summary 
            FROM evaluations 
            WHERE id = ?
            """,
            (evaluation_id,)
        )
        eval_result = cursor.fetchone()
        
        if not eval_result:
            logging.warning(f"No evaluation found with ID: {evaluation_id}")
            return jsonify({'error': 'Evaluation not found'}), 404
        
        # Extract resume text
        resume_path = eval_result[0]
        job_description = eval_result[2]
        profile_summary = eval_result[3]
        
        if not resume_path:
            return jsonify({'error': 'No resume path found for this evaluation'}), 400
        
        resume_text = extract_text_from_file(resume_path)
        if not resume_text:
            return jsonify({'error': 'Failed to extract text from resume'}), 400
        
        # Generate questions
        logging.info(f"Generating questions for resume: {resume_path}")
        questions_data = await async_generate_questions(
            resume_text,
            job_description,
            profile_summary
        )
        
        technical_questions = questions_data.get("TechnicalQuestions", [])
        nontechnical_questions = questions_data.get("NonTechnicalQuestions", [])
        behavioral_questions = QUICK_CHECKS
        
        # Save questions to database
        try:
            # First check if there's an existing entry
            cursor.execute(
                "SELECT id FROM interview_questions WHERE evaluation_id = ?",
                (evaluation_id,)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Update existing entry
                cursor.execute(
                    """
                    UPDATE interview_questions 
                    SET technical_questions = ?,
                        nontechnical_questions = ?,
                        behavioral_questions = ?
                    WHERE evaluation_id = ?
                    """,
                    (
                        json.dumps(technical_questions), 
                        json.dumps(nontechnical_questions), 
                        json.dumps(behavioral_questions), 
                        evaluation_id
                    )
                )
            else:
                # Insert new entry
                cursor.execute(
                    """
                    INSERT INTO interview_questions 
                    (evaluation_id, technical_questions, nontechnical_questions, behavioral_questions) 
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        evaluation_id,
                        json.dumps(technical_questions),
                        json.dumps(nontechnical_questions),
                        json.dumps(behavioral_questions)
                    )
                )
            
            conn.commit()
            logging.info(f"Saved questions for evaluation ID: {evaluation_id}")
        except Exception as e:
            logging.error(f"Error saving questions to database: {str(e)}")
            conn.rollback()
        
        # Return the generated questions
        return jsonify({
            'technical_questions': technical_questions,
            'nontechnical_questions': nontechnical_questions,
            'behavioral_questions': behavioral_questions
        })
        
    except Exception as e:
        logging.error(f"Error generating questions: {str(e)}")
        return jsonify({'error': str(e)}), 500
        
    finally:
        if conn:
            conn.close()

def get_default_interview_questions(job_title):
    """Generate default interview questions based on job title"""
    # Default technical questions based on common job titles
    technical_questions = {
        "software": [
            "Describe your experience with different programming languages and frameworks.",
            "How do you approach debugging a complex issue in your code?",
            "Explain your understanding of object-oriented programming principles.",
            "How do you ensure code quality and maintainability?",
            "Describe a challenging technical problem you solved recently."
        ],
        "data": [
            "Explain the difference between supervised and unsupervised learning.",
            "How do you handle missing or inconsistent data in your analysis?",
            "Describe your experience with SQL and database optimization.",
            "What tools and libraries do you use for data visualization?",
            "How do you validate the results of your data analysis?"
        ],
        "manager": [
            "How do you approach resource allocation in a project?",
            "Describe your experience with agile methodologies.",
            "How do you handle conflicts within your team?",
            "What metrics do you use to measure project success?",
            "How do you ensure your team meets deadlines and quality standards?"
        ],
        "analyst": [
            "Describe your approach to gathering requirements from stakeholders.",
            "How do you prioritize features or improvements?",
            "What tools do you use for data analysis and reporting?",
            "How do you communicate complex findings to non-technical stakeholders?",
            "Describe a situation where your analysis led to a significant business decision."
        ],
        "designer": [
            "How do you approach the design process for a new project?",
            "Describe your experience with different design tools and software.",
            "How do you incorporate user feedback into your designs?",
            "How do you balance aesthetics with functionality?",
            "Describe a design challenge you faced and how you overcame it."
        ]
    }
    
    # Default non-technical questions
    nontechnical_questions = [
        "How do you prioritize your work when dealing with multiple deadlines?",
        "Describe a situation where you had to collaborate with a difficult team member.",
        "How do you stay updated with the latest trends and developments in your field?",
        "Describe your ideal work environment and company culture.",
        "How do you handle feedback and criticism?"
    ]
    
    # Determine which set of technical questions to use based on job title
    job_title_lower = job_title.lower()
    selected_technical_questions = []
    
    if any(keyword in job_title_lower for keyword in ["developer", "engineer", "programmer", "software", "code", "web"]):
        selected_technical_questions = technical_questions["software"]
    elif any(keyword in job_title_lower for keyword in ["data", "analytics", "scientist", "ml", "ai"]):
        selected_technical_questions = technical_questions["data"]
    elif any(keyword in job_title_lower for keyword in ["manager", "director", "lead", "head"]):
        selected_technical_questions = technical_questions["manager"]
    elif any(keyword in job_title_lower for keyword in ["analyst", "business", "product"]):
        selected_technical_questions = technical_questions["analyst"]
    elif any(keyword in job_title_lower for keyword in ["designer", "ux", "ui", "graphic"]):
        selected_technical_questions = technical_questions["designer"]
    else:
        # If no match, use a mix of questions
        selected_technical_questions = [
            technical_questions["software"][0],
            technical_questions["analyst"][0],
            technical_questions["manager"][0],
            "Describe your technical skills that are most relevant to this position.",
            "What technical challenges are you looking forward to tackling in this role?"
        ]
    
    return selected_technical_questions, nontechnical_questions

if __name__ == "__main__":
    # Initialize database
    init_db()
    
    # Update database schema
    update_db_schema()
    
    # Initialize Pinecone and get vectorstore
    vectorstore = initialize_pinecone()
    
    # Build BM25 index
    build_bm25_index(POLICIES_FOLDER)
    
    # Set up LLM and QA chain
    llm, qa_chain, retriever = setup_llm_chain()
    
    # Start Flask server with ASGI support using hypercorn
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    config = Config()
    config.bind = ["localhost:5000"]
    config.use_reloader = True
    
    asyncio.run(serve(asgi_app, config))
