import os
import json
import pdfplumber
from anthropic import Anthropic

client = Anthropic()
MODEL = "claude-sonnet-4-6"

_SCHEMA_PROMPT = """Extract all information from this resume into JSON with these fields:
{
  "name": "string",
  "email": "string or null",
  "phone": "string or null",
  "location": "string or null",
  "headline": "string or null",
  "links": [
    {"platform": "GitHub|LinkedIn|Twitter|Website|Other", "url": "string"}
  ],
  "skills": ["string"],
  "experience": [
    {"company": "string", "role": "string", "duration": "string", "description": "string or null"}
  ],
  "education": [
    {"institution": "string", "degree": "string", "year": "string or null"}
  ],
  "certifications": ["string"],
  "projects": [
    {"name": "string", "description": "string or null", "url": "string or null"}
  ]
}

Resume:
"""


def _extract_text(file_path: str) -> str:
    ext = file_path.lower().split(".")[-1]
    if ext == "pdf":
        with pdfplumber.open(file_path) as pdf:
            pages = [p.extract_text() for p in pdf.pages if p.extract_text()]
            return "\n".join(pages)
    elif ext in ("docx", "doc"):
        from docx import Document
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    else:
        raise ValueError(f"Unsupported file type: .{ext} — use PDF or DOCX")


def parse_resume(file_path: str) -> dict:
    """Extract structured profile data from a resume file (PDF or DOCX)."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Resume not found: {file_path}")

    raw_text = _extract_text(file_path)

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{
            "type": "text",
            "text": "You are a resume parser. Extract structured data and return only valid JSON with no explanation.",
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": _SCHEMA_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": raw_text,
                },
            ],
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())
