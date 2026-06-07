from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


# rapidfuzz is optional. The app must still run on a fresh Windows/Streamlit setup
# even if the user has not installed optional fuzzy-matching packages.
try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    class _FuzzFallback:
        @staticmethod
        def token_set_ratio(a: str, b: str) -> float:
            a_tokens = set(str(a or "").split())
            b_tokens = set(str(b or "").split())
            if not a_tokens or not b_tokens:
                return 0.0
            common = " ".join(sorted(a_tokens & b_tokens))
            a_join = " ".join(sorted(a_tokens))
            b_join = " ".join(sorted(b_tokens))
            candidates = [
                SequenceMatcher(None, a_join, b_join).ratio(),
                SequenceMatcher(None, common, a_join).ratio() if common else 0.0,
                SequenceMatcher(None, common, b_join).ratio() if common else 0.0,
            ]
            return 100.0 * max(candidates)

    fuzz = _FuzzFallback()

@dataclass
class CandidateDocument:
    name: str
    path: str | None = None
    bytes_data: bytes | None = None
    match_score: float = 0.0
    extracted_text: str = ""
    page_count: int = 0
    checklist: dict[str, bool] | None = None

def normalize_token(s: Any) -> str:
    s = str(s or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).strip().casefold()
    return re.sub(r"\s+", " ", s)

def candidate_query_parts(candidate: dict) -> list[str]:
    parts = [candidate.get("Country of Residence", ""), candidate.get("Country of Citizenship", ""), candidate.get("First Name", ""), candidate.get("Surname", ""), candidate.get("Full Name", "")]
    return [normalize_token(p) for p in parts if normalize_token(p)]

def filename_match_score(filename: str, candidate: dict) -> float:
    name = normalize_token(filename)
    parts = candidate_query_parts(candidate)
    if not parts:
        return 0.0
    full = normalize_token(candidate.get("Full Name", ""))
    first = normalize_token(candidate.get("First Name", ""))
    surname = normalize_token(candidate.get("Surname", ""))
    country_res = normalize_token(candidate.get("Country of Residence", ""))
    country_cit = normalize_token(candidate.get("Country of Citizenship", ""))
    score = 0
    if first and first in name: score += 25
    if surname and surname in name: score += 35
    if country_res and country_res in name: score += 15
    if country_cit and country_cit in name: score += 15
    if "raun" in name and "application" in name: score += 10
    if full:
        score = max(score, fuzz.token_set_ratio(name, full) * 0.75)
    return min(100.0, float(score))

def extract_pdf_text_from_bytes(data: bytes, max_pages: int | None = None) -> tuple[str, int]:
    if fitz is None:
        return "", 0
    text_parts = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        page_count = doc.page_count
        limit = page_count if max_pages is None else min(page_count, max_pages)
        for i in range(limit):
            text_parts.append(doc.load_page(i).get_text("text"))
        doc.close()
        return "\n".join(text_parts), page_count
    except Exception:
        return "", 0

def extract_pdf_text_from_path(path: str | Path, max_pages: int | None = None) -> tuple[str, int]:
    try:
        return extract_pdf_text_from_bytes(Path(path).read_bytes(), max_pages=max_pages)
    except Exception:
        return "", 0

def build_document_checklist(text: str) -> dict[str, bool]:
    t = normalize_token(text)
    return {
        "CV / resume likely present": any(x in t for x in ["education", "professional experience", "work experience", "curriculum", "resume", "publications"]),
        "Motivation letter likely present": any(x in t for x in ["dear members", "selection committee", "motivation", "raun program", "raun programme"]),
        "Transcript / grades likely present": any(x in t for x in ["transcript", "grade", "grades", "ects", "certificate", "academic record"]),
        "Writing sample likely present": any(x in t for x in ["abstract", "introduction", "references", "works cited", "bibliography", "research paper"]),
        "Reference details likely present": any(x in t for x in ["references", "academic references", "referees", "reference"]),
    }

def load_local_pdf_documents(paths: Iterable[str | Path], candidate: dict | None = None, extract_text: bool = False) -> list[CandidateDocument]:
    docs = []
    for p in paths:
        path = Path(p)
        if not path.exists() or path.suffix.lower() != ".pdf":
            continue
        score = filename_match_score(path.name, candidate or {}) if candidate else 0.0
        text, pages = ("", 0)
        checklist = None
        if extract_text:
            text, pages = extract_pdf_text_from_path(path, max_pages=None)
            checklist = build_document_checklist(text)
        docs.append(CandidateDocument(path.name, str(path), None, score, text, pages, checklist))
    return sorted(docs, key=lambda d: d.match_score, reverse=True)

def uploaded_files_to_docs(uploaded_files: Iterable, candidate: dict | None = None, extract_text: bool = False) -> list[CandidateDocument]:
    docs = []
    for f in uploaded_files or []:
        if not str(f.name).lower().endswith(".pdf"):
            continue
        data = f.getvalue()
        score = filename_match_score(f.name, candidate or {}) if candidate else 0.0
        text, pages = ("", 0)
        checklist = None
        if extract_text:
            text, pages = extract_pdf_text_from_bytes(data, max_pages=None)
            checklist = build_document_checklist(text)
        docs.append(CandidateDocument(f.name, None, data, score, text, pages, checklist))
    return sorted(docs, key=lambda d: d.match_score, reverse=True)

def compact_candidate_context(candidate: dict, pdf_text: str = "", max_chars: int = 12000) -> str:
    fields = [
        "Full Name", "Email", "Program", "University", "Field", "Country of Residence", "Country of Citizenship",
        "Enrolled Master/PhD", "Current Professional Status", "Graduate Track Motivation", "Research Project Responsibility",
        "Self-rated Research Experience", "Self-rated Written English", "Self-rated Oral English", "Area 1", "Area 2", "Area 3",
        "Applied for Scholarship", "Scholarship Motivation", "Accessibility Requirements", "Accessibility Details",
    ]
    chunks = []
    for f in fields:
        v = str(candidate.get(f, "")).strip()
        if v:
            chunks.append(f"{f}: {v}")
    if pdf_text:
        chunks.append("PDF extracted text excerpt:\n" + pdf_text[:max_chars])
    return "\n\n".join(chunks)[:max_chars]
