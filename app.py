"""AI Resume ATS Checker - Streamlit app powered by OpenRouter."""

import io
import json
import os
import re
import time

import requests
import streamlit as st
from docx import Document
from pypdf import PdfReader

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/free"  # routes to a free model; change it in the sidebar
# Tried in order if the selected model is unavailable or does not exist.
FALLBACK_MODELS = ["openrouter/free"]
MAX_ATTEMPTS = 3  # tries per model; waits 2s, then 4s between tries
REQUEST_TIMEOUT = 120  # seconds
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

Remember: respond with the JSON object only.
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
# OpenRouter
# --------------------------------------------------------------------------- #
class OpenRouterError(RuntimeError):
    """An error with a message that is safe and useful to show to the user."""


class _Retryable(Exception):
    """Temporary problem (busy, rate limited, bad output): try again."""


class _BadModel(Exception):
    """This model name cannot be used: try the next one."""


def get_api_key() -> str:
    try:
        key = st.secrets.get("OPENROUTER_API_KEY", "")
    except Exception:
        key = ""
    return (key or os.getenv("OPENROUTER_API_KEY", "")).strip()


def _classify(code, message: str) -> Exception:
    """Map an OpenRouter error code to the right exception."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = 0
    message = message or "Unknown error"
    if code == 401:
        return OpenRouterError("OpenRouter rejected your API key. Check that it is correct and not expired.")
    if code == 402:
        return OpenRouterError(
            "This model needs OpenRouter credits and your account has none left. "
            "Add credits, or use a free model such as openrouter/free."
        )
    if code == 403:
        return OpenRouterError(f"OpenRouter refused the request: {message}")
    if code in (400, 404):
        return _BadModel(message)
    if code in (408, 429) or code >= 500 or code == 0:
        return _Retryable(f"{code or 'error'}: {message}")
    return OpenRouterError(f"OpenRouter error {code}: {message}")


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # some providers return a list of parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def call_openrouter(api_key: str, model: str, prompt: str) -> tuple:
    """One request. Returns (text, model_that_answered). Raises _Retryable, _BadModel or OpenRouterError."""
    base = os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "AI Resume ATS Checker",
        "X-OpenRouter-Title": "AI Resume ATS Checker",
    }
    referer = os.getenv("OPENROUTER_REFERER")
    if referer:
        headers["HTTP-Referer"] = referer
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(f"{base}/chat/completions", headers=headers, json=body, timeout=REQUEST_TIMEOUT)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        raise _Retryable(f"network problem: {e}")
    except requests.exceptions.RequestException as e:
        raise OpenRouterError(f"Could not reach OpenRouter: {e}")

    try:
        data = resp.json()
    except ValueError:
        data = None

    if not resp.ok:
        err = (data or {}).get("error") if isinstance(data, dict) else None
        message = err.get("message") if isinstance(err, dict) else resp.text[:200]
        raise _classify(resp.status_code, message)

    if not isinstance(data, dict):
        raise _Retryable("OpenRouter returned a response that was not JSON")

    # Errors can also arrive inside a 200 response.
    if isinstance(data.get("error"), dict):
        err = data["error"]
        raise _classify(err.get("code"), err.get("message"))
    choices = data.get("choices") or []
    if not choices:
        raise _Retryable("OpenRouter returned no choices")
    choice = choices[0] or {}
    if isinstance(choice.get("error"), dict):
        err = choice["error"]
        raise _classify(err.get("code"), err.get("message"))

    text = _content_to_text((choice.get("message") or {}).get("content"))
    if not text.strip():
        raise _Retryable("the model returned an empty answer")
    return text, data.get("model") or model


def parse_json_response(raw: str) -> dict:
    """Parse model output into a dict, tolerating markdown fences, <think> blocks or stray text."""
    if not raw:
        raise ValueError("The model returned an empty response.")
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("Could not parse the model response as JSON.")
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            raise ValueError("Could not parse the model response as JSON.")
    if not isinstance(parsed, dict):
        raise ValueError("The model response was not a JSON object.")
    return parsed


def _clamp_score(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def normalize_result(data: dict) -> dict:
    """Make sure every field the UI needs exists with a sane type."""
    sections = data.get("section_scores")
    sections = sections if isinstance(sections, dict) else {}
    return {
        "overall_score": _clamp_score(data.get("overall_score")),
        "summary": str(data.get("summary") or ""),
        "section_scores": {str(k): _clamp_score(v) for k, v in sections.items()},
        "strengths": [str(s) for s in _as_list(data.get("strengths"))],
        "improvements": [
            {
                "priority": str(i.get("priority", "Medium")).capitalize(),
                "issue": str(i.get("issue", "")),
                "suggestion": str(i.get("suggestion", "")),
            }
            for i in _as_list(data.get("improvements"))
            if isinstance(i, dict)
        ],
        "missing_keywords": [str(k) for k in _as_list(data.get("missing_keywords"))],
        "rewrite_examples": [
            {"original": str(r.get("original", "")), "improved": str(r.get("improved", ""))}
            for r in _as_list(data.get("rewrite_examples"))
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

    models = [model.strip() or DEFAULT_MODEL] + [m for m in FALLBACK_MODELS if m != model.strip()]
    last_error = None
    for name in models:
        for attempt in range(MAX_ATTEMPTS):
            try:
                text, used_model = call_openrouter(api_key, name, prompt)
                result = normalize_result(parse_json_response(text))
                result["model_used"] = used_model
                return result
            except _BadModel as e:
                last_error = e
                break  # this model name is not usable: go to the next one
            except (_Retryable, ValueError) as e:  # busy, or output was not valid JSON
                last_error = e
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** (attempt + 1))

    raise OpenRouterError(
        "OpenRouter is busy or the model did not give a usable answer. Wait a minute and click "
        f"Analyze again, or pick a different model in the sidebar. (Last error: {last_error})"
    )


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
        if result.get("model_used"):
            st.caption(f"Analyzed with {result['model_used']}")

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
            api_key = st.text_input(
                "OpenRouter API key", type="password", help="Create one at openrouter.ai/keys"
            ).strip()
        else:
            st.success("API key loaded")
        model = st.text_input(
            "Model",
            value=os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
            help="Any model ID from openrouter.ai/models. 'openrouter/free' picks a free model for you.",
        )
        st.info(
            "The score is an AI-based estimate, not the output of a real ATS. "
            "Use it as guidance for improving your resume."
        )
        st.warning(
            "Your resume text is sent to OpenRouter and the model provider. Free models may log "
            "prompts, so remove sensitive details (home address, ID numbers) first."
        )

    uploaded = st.file_uploader("Upload your resume", type=["pdf", "docx", "txt"])
    job_description = st.text_area(
        "Job description (optional, for a tailored score)",
        height=150,
        placeholder="Paste the job description here to check keyword match...",
    )

    if st.button("Analyze resume", type="primary", disabled=uploaded is None):
        if not api_key:
            st.error("Please provide an OpenRouter API key in the sidebar or app secrets.")
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
            with st.spinner("Analyzing your resume (this can take up to a minute)..."):
                st.session_state["result"] = analyze_resume(text, job_description, api_key, model)
        except (ValueError, RuntimeError) as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"Something went wrong while analyzing your resume: {e}")
            return

    if "result" in st.session_state:
        render_results(st.session_state["result"])


if __name__ == "__main__":
    main()
