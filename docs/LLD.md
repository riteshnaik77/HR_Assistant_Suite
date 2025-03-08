# HR Assistant Suite - Low-Level Design (LLD)

## 1. Database Schema

### 1.1 Evaluations Table
```sql
CREATE TABLE evaluations (
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
```

### 1.2 Interview Questions Table
```sql
CREATE TABLE interview_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id INTEGER,
    technical_questions TEXT,
    nontechnical_questions TEXT,
    behavioral_questions TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (evaluation_id) REFERENCES evaluations (id)
)
```

### 1.3 QA History Table
```sql
CREATE TABLE qa_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    retrieved_docs TEXT,
    final_answer TEXT,
    feedback TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### 1.4 Feedback Table
```sql
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id INTEGER,
    rating INTEGER,
    comments TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (evaluation_id) REFERENCES evaluations (id)
)
```

### 1.5 QA Feedback Table
```sql
CREATE TABLE qa_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER,
    rating INTEGER,
    feedback TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (question_id) REFERENCES qa_history (id)
)
```

## 2. API Endpoints

### 2.1 Resume Evaluation
- **Endpoint**: `/evaluate`
- **Method**: POST
- **Parameters**: 
  - `file`: Resume file
  - `job_title`: Job title
  - `job_description`: Job description
- **Response**: Evaluation results including match score, missing keywords, etc.
- **Implementation**: `evaluate_resume()` function in app.py

### 2.2 Interview Questions
- **Endpoint**: `/get_interview_questions/<evaluation_id>`
- **Method**: GET
- **Response**: Technical, non-technical, and behavioral questions
- **Implementation**: `get_interview_questions()` function in app.py

### 2.3 Evaluation Details
- **Endpoint**: `/api/evaluation/<evaluation_id>`
- **Method**: GET
- **Response**: Complete evaluation details including all analysis and questions
- **Implementation**: `get_evaluation_details()` function in app.py

### 2.4 Generate Questions
- **Endpoint**: `/api/generate_questions/<evaluation_id>`
- **Method**: POST
- **Response**: Newly generated interview questions
- **Implementation**: `generate_questions_api()` function in app.py

### 2.5 Feedback Submission
- **Endpoint**: `/api/feedback`
- **Method**: POST
- **Parameters**:
  - `evaluation_id`: ID of the evaluation
  - `rating`: Numerical rating
  - `comments`: Feedback comments
- **Response**: Success/failure status
- **Implementation**: `submit_feedback()` function in app.py

### 2.6 Ask Question
- **Endpoint**: `/api/ask`
- **Method**: POST
- **Parameters**:
  - `question`: User's question
- **Response**: AI-generated answer with supporting information
- **Implementation**: `ask_question()` function in app.py

## 3. Key Functions

### 3.1 Database Initialization
```python
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
    
    # Create other tables...
    
    conn.commit()
    conn.close()
```

### 3.2 Resume Processing
```python
def extract_text_from_file(file_path):
    """Extract text from various file formats (PDF, DOCX, etc.)"""
    # Implementation details for different file types
    # Return extracted text
```

### 3.3 Resume Analysis
```python
async def evaluate_resume():
    """Process resume evaluation request"""
    # Extract text from resume
    # Analyze resume against job description
    # Calculate match score
    # Identify missing keywords
    # Analyze job stability and career progression
    # Generate interview questions
    # Save results to database
    # Return results to user
```

### 3.4 Interview Question Generation
```python
async def async_generate_questions(resume_text, job_description, profile_summary):
    """Generate interview questions based on resume and job description"""
    # Generate technical questions based on resume and job
    # Generate non-technical questions
    # Return structured question data
```

### 3.5 Job Stability Analysis
```python
async def async_analyze_stability(resume_text):
    """Analyze job stability based on resume"""
    # Extract job history from resume
    # Calculate average tenure
    # Identify job hopping patterns
    # Determine stability score
    # Return structured stability data
```

### 3.6 Career Progression Analysis
```python
async def analyze_career_progression(resume_text):
    """Analyze career progression based on resume"""
    # Extract career path from resume
    # Identify promotions and lateral moves
    # Calculate progression score
    # Identify red flags and key observations
    # Return structured progression data
```

### 3.7 Data Retrieval
```python
def get_evaluation_details(evaluation_id):
    """Fetch evaluation details from database"""
    # Fetch evaluation details from database
    # Parse JSON data
    # Fetch interview questions
    # Return structured response
```

### 3.8 Data Storage
```python
def save_evaluation(eval_id, filename, job_title, rank_score, missing_keywords, profile_summary, match_factors, job_stability, additional_info=None):
    """Save evaluation results to database"""
    # Format data for storage
    # Insert into evaluations table
    # Return success/failure
```

## 4. Frontend Components

### 4.1 Resume Upload Form
- File upload input
- Job title and description fields
- Submit button
- Implementation: `resume-evaluator.html`

### 4.2 Evaluation Results Display
- Match score with progress bar
- Missing keywords section with badges
- Job stability analysis with metrics and visualization
- Career progression analysis with timeline
- Interview questions sections with categorized questions
- Implementation: JavaScript in `resume-evaluator.html`

### 4.3 History View
- Table of past evaluations with:
  - Resume filename
  - Job title
  - Match score
  - Date
  - Actions
- Modal for detailed view with tabbed interface
- Implementation: `history.html` and associated JavaScript

## 5. Error Handling

### 5.1 Database Errors
```python
try:
    # Database operations
    conn.commit()
except Exception as e:
    logging.error(f"Database error: {str(e)}")
    conn.rollback()
    return jsonify({'error': 'Database error'}), 500
finally:
    conn.close()
```

### 5.2 API Errors
```python
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Internal server error'}), 500
```

### 5.3 File Processing Errors
```python
def extract_text_from_file(file_path):
    try:
        # File processing logic
        return extracted_text
    except Exception as e:
        logging.error(f"Error extracting text from {file_path}: {str(e)}")
        return None
```

## 6. Data Models

### 6.1 Evaluation Model
```python
class Evaluation:
    def __init__(self, id, filename, job_title, match_percentage, profile_summary, 
                 missing_keywords, job_stability, career_progression, timestamp):
        self.id = id
        self.filename = filename
        self.job_title = job_title
        self.match_percentage = match_percentage
        self.profile_summary = profile_summary
        self.missing_keywords = missing_keywords
        self.job_stability = job_stability
        self.career_progression = career_progression
        self.timestamp = timestamp
```

### 6.2 Interview Questions Model
```python
class InterviewQuestions:
    def __init__(self, evaluation_id, technical_questions, nontechnical_questions, behavioral_questions):
        self.evaluation_id = evaluation_id
        self.technical_questions = technical_questions
        self.nontechnical_questions = nontechnical_questions
        self.behavioral_questions = behavioral_questions
```

## 7. Security Implementation

### 7.1 Input Validation
```python
def validate_file(file):
    if file and allowed_file(file.filename):
        return True
    return False

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
```

### 7.2 SQL Injection Prevention
```python
# Using parameterized queries
cursor.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,))
```

### 7.3 Error Handling
```python
try:
    # Operation that might fail
except Exception as e:
    # Log error but don't expose details to user
    logging.error(f"Error: {str(e)}")
    return jsonify({'error': 'An error occurred'}), 500
```

## 8. Performance Optimization

### 8.1 Asynchronous Processing
```python
@app.route('/evaluate', methods=['POST'])
async def evaluate_resume():
    # Asynchronous processing of resume
    result = await async_analyze_resume(resume_text)
    return jsonify(result)
```

### 8.2 Caching
```python
# Cache for frequently accessed data
evaluation_cache = {}

def get_cached_evaluation(evaluation_id):
    if evaluation_id in evaluation_cache:
        return evaluation_cache[evaluation_id]
    # Fetch from database if not in cache
```

### 8.3 Efficient Database Queries
```python
# Using specific column selection instead of SELECT *
cursor.execute('''
    SELECT id, filename, job_title, match_percentage 
    FROM evaluations 
    ORDER BY timestamp DESC
''')
```

## 9. Logging and Monitoring

### 9.1 Logging Configuration
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
```

### 9.2 Performance Logging
```python
def log_performance(function_name, start_time):
    end_time = time.time()
    execution_time = end_time - start_time
    logging.info(f"Function {function_name} executed in {execution_time:.2f} seconds")
```

### 9.3 Error Logging
```python
try:
    # Operation that might fail
except Exception as e:
    logging.error(f"Error in operation: {str(e)}", exc_info=True)
``` 