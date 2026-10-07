# AI-Resume
AI Resume ATS Checker

A Streamlit app that scores your resume for ATS (Applicant Tracking System) friendliness and suggests concrete improvements, powered by Google's Gemini Flash model.

Features
Upload a resume as PDF, DOCX or TXT
Overall ATS score (0-100) plus a breakdown by category
Strengths, prioritized improvements, and missing keywords
Before/after bullet rewrite examples
Optional job description input for a tailored keyword-match score

The score is an AI-based estimate, not the output of a real ATS. Use it as guidance.

Project structure
.
├── app.py
├── requirements.txt
└── README.md
Run locally
Get a free Gemini API key at https://aistudio.google.com/apikey
Install dependencies:
bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
Provide your API key (choose one):
Environment variable:
bash
     export GEMINI_API_KEY="your-key"      # Windows PowerShell: $env:GEMINI_API_KEY="your-key"
Or create .streamlit/secrets.toml:
toml
     GEMINI_API_KEY = "your-key"
Or just paste it into the sidebar when the app runs.
Start the app:
bash
   streamlit run app.py
Configuration
Setting	How	Default
GEMINI_API_KEY	env var or Streamlit secret	none (sidebar input if missing)
GEMINI_MODEL	env var, or edit in the sidebar	gemini-3.8-flash

Model names change often. If you get a "model not found" or access error, change the model in the sidebar (or set GEMINI_MODEL) to another current Flash model, e.g. gemini-3.6-flash or gemini-3.5-flash. See https://ai.google.dev/gemini-api/docs/models for the current list. Note that gemini-2.5-flash is restricted for new projects.

Deploy on Streamlit Community Cloud
Push this project to a GitHub repository (see below).
Go to https://share.streamlit.io and sign in with GitHub.
Click Create app, choose your repo, branch main, and main file app.py.
Open Advanced settings → Secrets and add:
toml
   GEMINI_API_KEY = "your-key"
Click Deploy.
Security

Never commit your API key. If you create .streamlit/secrets.toml locally, add it to .gitignore:

.streamlit/secrets.toml
venv/
__pycache__/
