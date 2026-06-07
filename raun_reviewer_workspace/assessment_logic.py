from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import math
import pandas as pd

PRE_OPTIONS_1_TO_5 = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
PRE_OPTIONS_0_TO_3 = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
INTERVIEW_OPTIONS_1_TO_5 = PRE_OPTIONS_1_TO_5
DECISION_OPTIONS = ["", "Yes", "Maybe", "No"]
YES_NO_OPTIONS = ["", "Yes", "No"]

PRE_FIELDS = [
    ("research", "Research/academic experience", PRE_OPTIONS_1_TO_5),
    ("international", "International experience & cultural awareness", PRE_OPTIONS_1_TO_5),
    ("english", "English proficiency", PRE_OPTIONS_1_TO_5),
    ("personality", "Personality / social orientation", PRE_OPTIONS_0_TO_3),
    ("motivation", "Motivation for participating in RAUN, interest in topics", PRE_OPTIONS_1_TO_5),
    ("grades", "University grades", PRE_OPTIONS_1_TO_5),
]

INTERVIEW_FIELDS = [
    ("motivation", "Motivation for participating in RAUN, interest in research theme"),
    ("international", "International experience & cultural awareness"),
    ("research", "Research / academic experiences"),
    ("professionalism", "Professionalism"),
    ("respect_diversity", "Respect for diversity"),
    ("communication_english", "Communication and English"),
    ("teamwork", "Team work"),
    ("planning_organization", "Planning & Organization"),
    ("availability", "Other obligations / availability"),
    ("un_knowledge", "UN knowledge"),
]

GUIDANCE = {
    "research": "5 = PhD/MA student with publications and work/internship research experience; 4 = publications/some research; 3 = MA with some research; 2 = limited; 1 = weak or unclear.",
    "international": "5 = extensive international work/study/volunteering and strong intercultural awareness; 4 = some exposure; 3 = limited exposure but clear awareness; 1-2 = little evidence.",
    "english": "5 = native/near-native; 4 = good with minor issues; 3 = understandable with noticeable mistakes; 1-2 = difficult to understand.",
    "personality": "0-3 only. 3 = strong volunteer/social engagement and positive impression; 2 = some engagement; 1 = limited evidence; 0 = none or concerning impression.",
    "motivation": "5 = excellent and tailored to RAUN/current theme; 4 = good but less complete; 3 = acceptable/generic; 1-2 = weak, generic, or not RAUN-related.",
    "grades": "5 = mostly excellent grades; 4 = many excellent/good; 3 = many satisfactory; 1-2 = mostly satisfactory or poor. Use a general transcript impression.",
}

INTERVIEW_GUIDANCE = {
    "motivation": "Assess how clearly the candidate explains their RAUN motivation and fit with the current theme.",
    "international": "Assess international exposure, intercultural awareness, and ability to work across cultures.",
    "research": "Assess research maturity, ability to discuss methods, academic writing, and independent project experience.",
    "professionalism": "Assess maturity, reliability, seriousness, and professional conduct.",
    "respect_diversity": "Assess openness, integrity, and respectful engagement with diverse people and perspectives.",
    "communication_english": "Assess spoken clarity, listening, structure, and English proficiency.",
    "teamwork": "Assess collaboration, conflict resilience, remote teamwork readiness, and supportiveness.",
    "planning_organization": "Assess organization, time management, commitments, and structured thinking.",
    "availability": "Assess whether the candidate can attend all sessions and balance RAUN with studies/work.",
    "un_knowledge": "Assess basic UN knowledge without making it the dominant criterion.",
}

def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default

def round_half(x: float) -> float:
    return round(float(x) * 2.0) / 2.0

def normalize_decision(value: Any) -> str:
    s = str(value or "").strip().casefold()
    if s in {"yes", "y", "invite", "invited", "true", "1"}:
        return "Yes"
    if s in {"maybe", "borderline", "panel review", "m"}:
        return "Maybe"
    if s in {"no", "n", "do not invite", "false", "0"}:
        return "No"
    return ""

def normalize_yes_no(value: Any) -> str:
    s = str(value or "").strip().casefold()
    if s in {"yes", "y", "true", "1", "x"}:
        return "Yes"
    if s in {"no", "n", "false", "0"}:
        return "No"
    return ""

def preselection_total(row_or_dict: dict, prefix: str = "") -> float:
    keys = ["research", "international", "english", "personality", "motivation", "grades"]
    total = 0.0
    for k in keys:
        total += to_float(row_or_dict.get(f"{prefix}{k}"), 0.0)
    return round_half(total)

def derive_score_decision(total: float) -> str:
    total = to_float(total, 0.0)
    if total >= 20:
        return "Yes"
    if total >= 16:
        return "Maybe"
    if total > 0:
        return "No"
    return ""

def derive_first_review_result(r1_decision: Any, r2_decision: Any) -> str:
    r1 = normalize_decision(r1_decision)
    r2 = normalize_decision(r2_decision)
    if not r1 and not r2:
        return ""
    if r1 == "Yes" and r2 == "Yes":
        return "Yes"
    if r1 == "No" and r2 == "No":
        return "No"
    if r1 == "Maybe" and r2 == "Maybe":
        return "Maybe"
    if {r1, r2} == {"Maybe", "Yes"}:
        return "Maybe+Yes"
    if not r1 or not r2:
        return "Pending"
    return "Maybe+No"

def interview_required_from_result(result: Any) -> str:
    return "No" if str(result or "").strip() == "No" else "Yes"

def interview_total(row_or_dict: dict, prefix: str = "int_") -> float:
    total = 0.0
    for key, _ in INTERVIEW_FIELDS:
        total += to_float(row_or_dict.get(f"{prefix}{key}"), 0.0)
    return round_half(total)

def interview_band(score: float) -> str:
    score = to_float(score, 0.0)
    if score >= 41:
        return "Highly recommended"
    if score >= 31:
        return "Recommended"
    if score >= 21:
        return "Moderately recommended"
    if score > 0:
        return "Not recommended"
    return "Pending"

def final_band(score: float) -> str:
    score = to_float(score, 0.0)
    if score >= 85:
        return "Highly recommended"
    if score >= 70:
        return "Recommended"
    if score >= 55:
        return "Reserve / panel review"
    if score > 0:
        return "Not recommended"
    return "Pending"

def is_completed(decision: Any, total: Any) -> bool:
    return bool(normalize_decision(decision)) or to_float(total, 0.0) > 0

def preselection_guidance_markdown() -> str:
    return """
**Pre-selection guidance**

- Research / academic experience: 1 to 5.
- International experience & cultural awareness: 1 to 5.
- English proficiency: 1 to 5.
- Personality / social orientation: 0 to 3 only.
- Motivation: 1 to 5.
- University grades: 1 to 5.

Half-points are allowed. The maximum pre-selection score per reviewer is 28. The invitation decision should be stored as **Yes**, **Maybe**, or **No**.
"""
