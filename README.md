# HR Assistant Suite

A comprehensive web application designed to streamline HR processes, particularly resume evaluation and interview preparation, powered by AI.

## Features

- **Resume Evaluation**
  - Analyze resumes against job descriptions
  - Calculate match scores and identify missing keywords
  - Generate job stability and career progression analysis
  - Provide tailored interview questions

- **HR Assistant**
  - AI-powered assistance for HR-related queries
  - Access to HR policies and guidelines
  - Real-time responses with context-aware answers

- **History Viewer**
  - Track past evaluations and their details
  - Access historical interview questions
  - Review previous analyses

## Tech Stack

- **Backend**: Python/Flask
- **AI/ML**: Google Gemini, Groq
- **Database**: SQLite
- **Vector Store**: Pinecone
- **Document Processing**: pdfplumber, python-docx
- **Frontend**: HTML/CSS/JavaScript, Bootstrap

## Installation

1. Clone the repository:
```bash
git clone [your-repository-url]
cd hr-assistant-suite
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
Create a `.env` file with:
```
GROQ_API_KEY=your_groq_api_key
PINECONE_API_KEY=your_pinecone_api_key
GEMINI_API_KEY=your_gemini_api_key
```

5. Initialize the database:
```bash
python app.py
```

## Usage

1. Start the server:
```bash
python run.py
```

2. Access the application at `http://localhost:5000`

3. Available endpoints:
- `/`: Main dashboard
- `/hr-assistant`: HR query interface
- `/resume-evaluator`: Resume evaluation tool
- `/history`: View evaluation history

## Project Structure

```
├── app.py              # Main application file
├── docs/              
│   ├── HLD.md         # High-level design documentation
│   └── LLD.md         # Low-level design documentation
├── templates/          # HTML templates
├── uploads/           # Temporary storage for uploaded files
├── HR_docs/           # HR policy documents
└── requirements.txt   # Project dependencies
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

apache2.0

## Contact

[riteshnaik77@gmail.com]
