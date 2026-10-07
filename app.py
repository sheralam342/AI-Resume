""AI Resume ATS Checker - Streamlit app powered by Google Gemini Flash."""
 
import io
import json
import os
import re
 
import streamlit as st
from docx import Document
from google import genai
from google.genai import types
from pypdf import PdfReader
 
DEFAULT_MODEL = "gemini-3.8-flash"  # editable in the sidebar if Google renames/retires it
MAX_RESUME_CHARS = 20000
MIN_RESUME_CHARS = 150
 
PROMPT_TEMPLATE = """You are an expert ATS (Applicant Tracking System) analyst and professional resume reviewer.
 
Analyze the resume below and return ONLY a valid JSON object (no markdown, no commentary) with exactly this schema:
 
{{
  "overall_score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "section_scores": {{
    "formatting_and_parsability": <integer 0-100>,
    "keywords_and_skills": <integer 0-100>,
    "impact_and_achievements": <integer 0-100>,
    "clarity_and_language": <integer 0-100>,
    "structure_and_completeness": <integer 0-100>
  }},
  "strengths": ["<short strength>", "..."],
  "improvements": [
    {{
      "priority": "High" | "Medium" | "Low",
      "issue": "<what is wrong>",
      "suggestion": "<specific, actionable fix>"
    }}
  ],
  "missing_keywords": ["<keyword or skill that should be added>", "..."],
  "rewrite_examples": [
    {{
      "original": "<weak bullet copied from the resume>",
      "improved": "<stronger rewrite using action verbs and measurable impact>"
    }}
  ]
}}
 
Scoring guidance:
- Be realistic and strict. 90+ is rare. Most resumes score between 45 and 80.
- Consider: standard section headings, contact info, consistent dates, quantified achievements,
  strong action verbs, relevant keywords, length, spelling/grammar, and anything that would confuse an ATS parser.
- Give 4-8 improvements ordered by priority, 3-5 strengths, up to 12 missing keywords and up to 3 rewrite examples.
{jd_instructions}
{jd_block}
RESUME TEXT:
\"\"\"
{resume_text}
\"\"\"
"""
 
JD_INSTRUCTIONS = (
    "- A job description is provided. Score keyword match and relevance against it, and make "
    "missing_keywords reflect terms from the job description that the resume lacks."
)
 
 
# --------------------------------------------------------------------------- #
# File parsing
# --------------------------------------------------------------------------- #
def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("") != 0  # 0 means the empty password failed
        except Exception:
            unlocked = False
        if not unlocked:
            raise ValueError("This PDF is password protected. Please upload an unlocked copy.")
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages).strip()
 
 
def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts).strip()
 
 
def extract_resume_text(filename: str, file_bytes: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        text = extract_text_from_pdf(file_bytes)
    elif name.endswith(".docx"):
        text = extract_text_from_docx(file_bytes)
    elif name.endswith(".txt"):
        text = file_bytes.decode("utf-8", errors="ignore").strip()
    else:
        raise ValueError("Unsupported file type. Please upload a PDF, DOCX or TXT file.")
    return re.sub(r"\n{3,}", "\n\n", text)
 
 
# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #
def get_api_key() -> str:
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return key or os.getenv("GEMINI_API_KEY", "")
 
 
def parse_json_response(raw: str) -> dict:
    """Parse model output into a dict, tolerating markdown fences or stray text."""
    if not raw:
        raise ValueError("The model returned an empty response.")
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise ValueError("Could not parse the model response as JSON.")
 
 
def _clamp_score(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0
 
 
def normalize_result(data: dict) -> dict:
    """Make sure every field the UI needs exists with a sane type."""
    sections = data.get("section_scores") or {}
    return {
        "overall_score": _clamp_score(data.get("overall_score")),
        "summary": str(data.get("summary", "")),
        "section_scores": {str(k): _clamp_score(v) for k, v in sections.items()},
        "strengths": [str(s) for s in (data.get("strengths") or [])],
        "improvements": [
            {
                "priority": str(i.get("priority", "Medium")).capitalize(),
                "issue": str(i.get("issue", "")),
                "suggestion": str(i.get("suggestion", "")),
            }
            for i in (data.get("improvements") or [])
            if isinstance(i, dict)
        ],
        "missing_keywords": [str(k) for k in (data.get("missing_keywords") or [])],
        "rewrite_examples": [
            {"original": str(r.get("original", "")), "improved": str(r.get("improved", ""))}
            for r in (data.get("rewrite_examples") or [])
            if isinstance(r, dict)
        ],
    }
 
 
def analyze_resume(resume_text: str, job_description: str, api_key: str, model: str) -> dict:
    jd = job_description.strip()
    prompt = PROMPT_TEMPLATE.format(
        jd_instructions=JD_INSTRUCTIONS if jd else "",
        jd_block=f'JOB DESCRIPTION:\n"""\n{jd[:8000]}\n"""\n' if jd else "",
        resume_text=resume_text[:MAX_RESUME_CHARS],
    )
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    return normalize_result(parse_json_response(response.text))
 
 
# --------------------------------------------------------------------------- #
# UI helpers
# --------------------------------------------------------------------------- #
def score_label(score: int) -> str:
    if score >= 80:
        return "Excellent"
    if score >= 65:
        return "Good"
    if score >= 50:
        return "Needs work"
    return "Poor"
 
 
def pretty(name: str) -> str:
    return name.replace("_", " ").title()
 
 
def render_results(result: dict) -> None:
    score = result["overall_score"]
    left, right = st.columns([1, 3])
    left.metric("ATS Score", f"{score}/100", score_label(score))
    with right:
        st.progress(score / 100)
        if result["summary"]:
            st.write(result["summary"])
 
    if result["section_scores"]:
        st.subheader("Score breakdown")
        cols = st.columns(len(result["section_scores"]))
        for col, (name, value) in zip(cols, result["section_scores"].items()):
            col.metric(pretty(name), f"{value}")
            col.progress(value / 100)
 
    if result["strengths"]:
        st.subheader("Strengths")
        for s in result["strengths"]:
            st.markdown(f"- {s}")
 
    if result["improvements"]:
        st.subheader("Improvements")
        order = {"High": 0, "Medium": 1, "Low": 2}
        icons = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}
        for item in sorted(result["improvements"], key=lambda i: order.get(i["priority"], 1)):
            with st.expander(f"{icons.get(item['priority'], '🟠')} {item['priority']}: {item['issue']}"):
                st.write(item["suggestion"])
 
    if result["missing_keywords"]:
        st.subheader("Keywords to consider adding")
        st.write("  ".join(f"`{k}`" for k in result["missing_keywords"]))
 
    if result["rewrite_examples"]:
        st.subheader("Sample rewrites")
        for ex in result["rewrite_examples"]:
            st.markdown(f"**Before:** {ex['original']}")
            st.markdown(f"**After:** {ex['improved']}")
            st.divider()
 
 
# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(page_title="AI Resume ATS Checker", page_icon="📄", layout="wide")
    st.title("📄 AI Resume ATS Checker")
    st.caption("Upload your resume to get an estimated ATS score and concrete ways to improve it.")
 
    api_key = get_api_key()
    with st.sidebar:
        st.header("Settings")
        if not api_key:
            api_key = st.text_input("Gemini API key", type="password", help="Get one free at aistudio.google.com")
        else:
            st.success("API key loaded")
        model = st.text_input("Gemini model", value=os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
        st.info(
            "The score is an AI-based estimate, not the output of a real ATS. "
            "Use it as guidance for improving your resume."
        )
 
    uploaded = st.file_uploader("Upload your resume", type=["pdf", "docx", "txt"])
    job_description = st.text_area(
        "Job description (optional, for a tailored score)",
        height=150,
        placeholder="Paste the job description here to check keyword match...",
    )
 
    if st.button("Analyze resume", type="primary", disabled=uploaded is None):
        if not api_key:
            st.error("Please provide a Gemini API key in the sidebar or app secrets.")
            return
        try:
            with st.spinner("Reading your resume..."):
                text = extract_resume_text(uploaded.name, uploaded.getvalue())
            if len(text) < MIN_RESUME_CHARS:
                st.error(
                    "Very little text could be extracted. If your resume is a scanned image, "
                    "that is also a problem for real ATS systems. Please upload a text-based PDF or DOCX."
                )
                return
            with st.spinner("Analyzing with Gemini..."):
                st.session_state["result"] = analyze_resume(text, job_description, api_key, model)
        except ValueError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"Something went wrong while analyzing your resume: {e}")
            return
 
    if "result" in st.session_state:
        render_results(st.session_state["result"])
 
 
if __name__ == "__main__":
    main()
