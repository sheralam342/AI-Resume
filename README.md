# AI Resume ATS Checker (OpenRouter)

A Streamlit app that scores your resume for ATS (Applicant Tracking System) friendliness and suggests concrete improvements, using any AI model available on [OpenRouter](https://openrouter.ai).

## Features

- Upload a resume as **PDF, DOCX or TXT**
- Overall **ATS score (0-100)** plus a breakdown by category
- Strengths, prioritized improvements, and missing keywords
- Before/after **bullet rewrite examples**
- Optional **job description** input for a tailored keyword-match score
- Automatic retries when a model is busy or rate limited

> The score is an AI-based estimate, not the output of a real ATS. Use it as guidance.

## Project structure

```
.
├── app.py
├── requirements.txt      <- must be named exactly this (with an "s")
└── README.md
```

## Run locally

1. Create a free API key at https://openrouter.ai/keys
2. Install dependencies:

   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Provide your API key (choose one):

   - Environment variable:
     ```bash
     export OPENROUTER_API_KEY="your-key"      # Windows PowerShell: $env:OPENROUTER_API_KEY="your-key"
     ```
   - Or create `.streamlit/secrets.toml`:
     ```toml
     OPENROUTER_API_KEY = "your-key"
     ```
   - Or just paste it into the sidebar when the app runs.

4. Start the app:

   ```bash
   streamlit run app.py
   ```

## Configuration

| Setting | How | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | env var or Streamlit secret | none (sidebar input if missing) |
| `OPENROUTER_MODEL` | env var, or edit in the sidebar | `openrouter/free` |
| `OPENROUTER_REFERER` | env var (optional, your site URL) | none |

### Choosing a model

- `openrouter/free` lets OpenRouter pick a free model for you. It needs no credits, but free models are rate limited and quality varies from run to run.
- For steadier results, paste any model ID from https://openrouter.ai/models into the sidebar (for example a paid model). Paid models need credits in your OpenRouter account.
- Model names change often. If you see a "not found" style error, pick another ID from the models page.

## Deploy on Streamlit Community Cloud

1. Push this project to a GitHub repository (see below).
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click **Create app**, choose your repo, branch `main`, and main file `app.py`.
4. Open **Advanced settings → Secrets** and add:
   ```toml
   OPENROUTER_API_KEY = "your-key"
   ```
5. Click **Deploy**.

If the app shows `ModuleNotFoundError`, check that `requirements.txt` is in the repo root and named exactly that.

## Privacy

Resume text is sent to OpenRouter and the model provider behind it. Free models may log prompts, so remove sensitive details such as your home address or ID numbers before uploading.

## Security

Never commit your API key. If you create `.streamlit/secrets.toml` locally, add it to `.gitignore`:

```
.streamlit/secrets.toml
venv/
__pycache__/
```
