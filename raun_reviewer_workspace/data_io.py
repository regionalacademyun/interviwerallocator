from __future__ import annotations
import io
import re
import unicodedata
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from .assessment_logic import (
    derive_first_review_result,
    interview_required_from_result,
    normalize_decision,
    normalize_yes_no,
    preselection_total,
)

warnings.filterwarnings("ignore", message="Unknown extension is not supported and will be removed", category=UserWarning, module="openpyxl")

CANONICAL_BASE_COLUMNS = [
    "Applicant ID", "Source Row Number", "Reviewer 1", "Reviewer 2", "Interviewer",
    "First Name", "Middle Name", "Surname", "Full Name", "Gender", "Date of Birth", "Age",
    "Country of Residence", "Country of Citizenship", "Email", "Enrolled Master/PhD", "Program",
    "University", "Field", "Current Professional Status", "Graduate Track Motivation", "Previous Application",
    "Previous Application Years", "Previous Interview Invitation", "Research Project Responsibility",
    "Self-rated Research Experience", "Self-rated Written English", "Self-rated Oral English", "Area 1", "Area 2", "Area 3",
    "Applied for Scholarship", "Participate Without Scholarship", "Scholarship Motivation",
    "Accessibility Requirements", "Accessibility Details",
]

PRE_EXPORT_COLUMNS = [
    "R1 Research", "R1 International", "R1 English", "R1 Personality", "R1 Motivation", "R1 Grades", "R1 Total", "R1 Invitation", "R1 Top5", "R1 Comment",
    "R2 Research", "R2 International", "R2 English", "R2 Personality", "R2 Motivation", "R2 Grades", "R2 Total", "R2 Invitation", "R2 Top5", "R2 Comment",
    "Total points from Reviewer 1", "Total points from Reviewer 2", "Total points from both reviewers", "Derived First Review Result", "Interview Required",
]

INTERVIEW_EXPORT_COLUMNS = [
    "Interview Motivation", "Interview International", "Interview Research", "Interview Professionalism", "Interview Respect Diversity",
    "Interview Communication English", "Interview Teamwork", "Interview Planning Organization", "Interview Availability", "Interview UN Knowledge",
    "Interview Total", "Interview Recommended", "Interview Top5", "Interview Comment", "Final Total", "Final Decision",
]

def normalize_text(value: Any) -> str:
    s = str(value or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s.casefold().strip()

def normalize_header(value: Any) -> str:
    s = normalize_text(value)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def make_unique_headers(headers: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, h in enumerate(headers):
        base = str(h).strip() if str(h).strip() and not str(h).startswith("Unnamed") else f"Unnamed {i+1}"
        if base in seen:
            seen[base] += 1
            out.append(f"{base}__{seen[base]}")
        else:
            seen[base] = 0
            out.append(base)
    return out

def _looks_like_header(row: pd.Series) -> int:
    joined = " | ".join([str(x) for x in row.tolist() if str(x) != "nan"])
    score = 0
    for token in ["Reviewer 1", "Reviewer 2", "First name", "Surname", "E-Mail", "University", "Research/academic"]:
        if token.casefold() in joined.casefold():
            score += 1
    return score

def read_tabular_file(uploaded_or_path: Any, sheet_name: str | int | None = 0) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    name = getattr(uploaded_or_path, "name", str(uploaded_or_path))
    suffix = Path(name).suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        raw_no_header = pd.read_excel(uploaded_or_path, sheet_name=sheet_name if sheet_name not in {None, ""} else 0, header=None, engine="openpyxl")
        header_idx = max(range(min(8, len(raw_no_header))), key=lambda i: _looks_like_header(raw_no_header.iloc[i]))
        raw_df = pd.read_excel(uploaded_or_path, sheet_name=sheet_name if sheet_name not in {None, ""} else 0, header=header_idx, engine="openpyxl")
    else:
        raw_probe = pd.read_csv(uploaded_or_path, header=None)
        header_idx = max(range(min(8, len(raw_probe))), key=lambda i: _looks_like_header(raw_probe.iloc[i]))
        uploaded_or_path.seek(0) if hasattr(uploaded_or_path, "seek") else None
        raw_df = pd.read_csv(uploaded_or_path, header=header_idx)
    raw_df.columns = make_unique_headers(list(raw_df.columns))
    raw_df = raw_df.dropna(how="all").reset_index(drop=True)
    meta = {"source_name": name, "header_row_index_zero_based": int(header_idx), "data_start_excel_row": int(header_idx + 2)}
    normalized = normalize_assessment_dataframe(raw_df, meta)
    return raw_df, normalized, meta

def find_exact_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    norm_map = {normalize_header(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_header(cand)
        if n in norm_map:
            return norm_map[n]
    return None

def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    norm_map = {normalize_header(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_header(cand)
        if n in norm_map:
            return norm_map[n]
    for cand in candidates:
        n = normalize_header(cand)
        for key, col in norm_map.items():
            if n and n in key:
                return col
    return None

def find_occurrence_cols(df: pd.DataFrame, base_candidates: list[str]) -> list[str]:
    """Return repeated reviewer-block columns for a specific criterion.

    Matching is intentionally stricter than find_col because short/empty
    normalized headers such as "#" must never match every criterion.
    """
    matches = []
    wanted = [normalize_header(x) for x in base_candidates if normalize_header(x)]
    for col in df.columns:
        base = re.sub(r"(__\d+|\.\d+)$", "", str(col)).strip()
        ncol = normalize_header(base)
        if not ncol or ncol.startswith("unnamed"):
            continue
        if any(w == ncol or (len(w) > 8 and w in ncol) for w in wanted):
            matches.append(col)
    return matches

def get_value(row: pd.Series, col: str | None, default: Any = "") -> Any:
    if col and col in row.index:
        val = row[col]
        if pd.isna(val):
            return default
        return val
    return default

def clean_name_part(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "").replace("nan", "")).strip()

def build_full_name(row: pd.Series, col_first: str | None, col_middle: str | None, col_surname: str | None) -> str:
    parts = [clean_name_part(get_value(row, col_first)), clean_name_part(get_value(row, col_middle)), clean_name_part(get_value(row, col_surname))]
    return re.sub(r"\s+", " ", " ".join([p for p in parts if p])).strip()

def _num_or_blank(v: Any) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return ""
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return v

def normalize_assessment_dataframe(raw_df: pd.DataFrame, meta: dict | None = None) -> pd.DataFrame:
    meta = meta or {}
    df = raw_df.copy()

    col_id = find_col(df, ["#", "Applicant ID", "ID"])
    col_r1 = find_col(df, ["Reviewer 1"])
    col_r2 = find_col(df, ["Reviewer 2"])
    col_interviewer = find_col(df, ["Interviewer", "Interview Reviewer"])
    col_first = find_col(df, ["First name(s)", "First Name", "Given Name"])
    col_middle = find_col(df, ["Middle name(s)", "Middle Name"])
    col_surname = find_col(df, ["Surname", "Last Name", "Family Name"])
    col_email = find_col(df, ["E-Mail", "Email", "E-mail address"])

    direct = {
        "Gender": ["Gender"],
        "Date of Birth": ["Date of birth", "DOB"],
        "Age": ["Age"],
        "Country of Residence": ["Country of residence"],
        "Country of Citizenship": ["Country of citizenship", " Country of citizenship"],
        "Enrolled Master/PhD": ["Are you currently enrolled in a Master or PhD program?"],
        "Program": ["MA/PHD", "Program", "Programme"],
        "University": ["University"],
        "Field": ["Major/Field", "Major", "Field"],
        "Current Professional Status": ["Current professional status"],
        "Graduate Track Motivation": ["Please briefly explain your motivation for applying under the Graduate Track"],
        "Previous Application": ["Have you previously applied to the RAUN programme?"],
        "Previous Application Years": ["If yes, in which year(s) did you previously apply?"],
        "Previous Interview Invitation": ["If yes, were you invited to an interview during your previous application?"],
        "Research Project Responsibility": ["Have you ever been responsible for conducting a research project"],
        "Self-rated Research Experience": ["How would you rate your experience in conducting research?"],
        "Self-rated Written English": ["How would you rate your proficiency in written English communication?"],
        "Self-rated Oral English": ["How would you rate your proficiency in oral English communication?"],
        "Area 1": ["Area 1"],
        "Area 2": ["Area 2"],
        "Area 3": ["Area 3"],
        "Applied for Scholarship": ["Applied for scholarship?"],
        "Participate Without Scholarship": ["Would you still be willing to participate in the Academy if you do NOT receive the scholarship?"],
        "Scholarship Motivation": ["Why you are applying for a scholarship?"],
        "Accessibility Requirements": ["Do you have any accessibility requirements or special needs"],
        "Accessibility Details": ["If yes, please briefly describe your requirements"],
    }
    direct_cols = {out: find_col(df, cands) for out, cands in direct.items()}

    score_occurrences = {
        "Research": find_occurrence_cols(df, ["Research/academic experience"]),
        "International": find_occurrence_cols(df, ["international experience & cultural awareness"]),
        "English": find_occurrence_cols(df, ["English proficiency"]),
        "Personality": find_occurrence_cols(df, ["Personality / social orientation"]),
        "Motivation": find_occurrence_cols(df, ["Motivation for participating in RAUN, interest in topics"]),
        "Grades": find_occurrence_cols(df, ["University grades"]),
        "Total": find_occurrence_cols(df, ["Total Points"]),
        "Invitation": find_occurrence_cols(df, ["Invitation to interview?"]),
        "Top5": find_occurrence_cols(df, ["your top-5?", "your top 5"]),
        "Comment": find_occurrence_cols(df, ["Comment"]),
    }

    summary_r1 = find_col(df, ["Total points from Reviewer 1"])
    summary_r2 = find_col(df, ["Total points from Reviewer 2"])
    summary_both = find_col(df, ["Total points from both reviewers"])

    # Interview columns must be exact or near-exact. Do not let short labels such as
    # "Motivation" match long pre-selection/application text fields.
    interview_map = {
        "Interview Motivation": find_exact_col(df, ["Motivation", "Interview Motivation"]),
        "Interview International": find_exact_col(df, ["International experience", "Interview International"]),
        "Interview Research": find_exact_col(df, ["Research/ Academic experience", "Research Academic experience", "Interview Research"]),
        "Interview Professionalism": find_exact_col(df, ["Professionalism", "Interview Professionalism"]),
        "Interview Respect Diversity": find_exact_col(df, ["Respect for diversity", "Interview Respect Diversity"]),
        "Interview Communication English": find_exact_col(df, ["Communication and English", "Interview Communication English"]),
        "Interview Teamwork": find_exact_col(df, ["Team work", "Interview Teamwork"]),
        "Interview Planning Organization": find_exact_col(df, ["Planning& Organization", "Planning Organization", "Interview Planning Organization"]),
        "Interview Availability": find_exact_col(df, ["Other obligations/ availability", "Other obligations availability", "Interview Availability"]),
        "Interview UN Knowledge": find_exact_col(df, ["UN knowledge", "Interview UN Knowledge"]),
        "Interview Total": find_exact_col(df, ["Total points (0-50)", "Total points interview", "Interview Total"]),
        "Interview Recommended": find_exact_col(df, ["Recommended?", "Interview Recommended"]),
        "Interview Comment": find_exact_col(df, ["Interview Comment"]),
        "Final Total": find_exact_col(df, ["Grand Total", "Final Total"]),
        "Final Decision": find_exact_col(df, ["Final Decision"]),
    }

    rows = []
    for idx, row in df.iterrows():
        full_name = build_full_name(row, col_first, col_middle, col_surname)
        if not full_name and not get_value(row, col_email):
            continue
        applicant_id = get_value(row, col_id, idx + 1)
        try:
            applicant_id = int(float(applicant_id))
        except Exception:
            applicant_id = idx + 1
        out = {c: "" for c in CANONICAL_BASE_COLUMNS + PRE_EXPORT_COLUMNS + INTERVIEW_EXPORT_COLUMNS}
        out["Applicant ID"] = applicant_id
        out["Source Row Number"] = int(idx + meta.get("data_start_excel_row", 2))
        out["Reviewer 1"] = get_value(row, col_r1)
        out["Reviewer 2"] = get_value(row, col_r2)
        out["Interviewer"] = get_value(row, col_interviewer)
        out["First Name"] = get_value(row, col_first)
        out["Middle Name"] = get_value(row, col_middle)
        out["Surname"] = get_value(row, col_surname)
        out["Full Name"] = full_name
        out["Email"] = get_value(row, col_email)
        # Preserve every original Excel/Google Forms cell so reviewers can inspect the complete row.
        # Prefix avoids collisions with normalized fields and makes the source fields clear in the UI/export.
        for raw_col in df.columns:
            out[f"Excel: {raw_col}"] = get_value(row, raw_col)
        for out_col, src_col in direct_cols.items():
            out[out_col] = get_value(row, src_col)
        for label in ["Research", "International", "English", "Personality", "Motivation", "Grades", "Total", "Invitation", "Top5", "Comment"]:
            cols = score_occurrences.get(label, [])
            if len(cols) > 0:
                out[f"R1 {label}"] = get_value(row, cols[0])
            if len(cols) > 1:
                out[f"R2 {label}"] = get_value(row, cols[1])
        out["R1 Invitation"] = normalize_decision(out["R1 Invitation"])
        out["R2 Invitation"] = normalize_decision(out["R2 Invitation"])
        out["R1 Top5"] = normalize_yes_no(out["R1 Top5"])
        out["R2 Top5"] = normalize_yes_no(out["R2 Top5"])
        calc_r1 = preselection_total({k.lower().replace("r1 ", ""): out[k] for k in ["R1 Research", "R1 International", "R1 English", "R1 Personality", "R1 Motivation", "R1 Grades"]})
        calc_r2 = preselection_total({k.lower().replace("r2 ", ""): out[k] for k in ["R2 Research", "R2 International", "R2 English", "R2 Personality", "R2 Motivation", "R2 Grades"]})
        out["R1 Total"] = _num_or_blank(out["R1 Total"] or calc_r1)
        out["R2 Total"] = _num_or_blank(out["R2 Total"] or calc_r2)
        out["R1 Invitation"] = out["R1 Invitation"] or ("" if not out["R1 Total"] else normalize_decision(out["R1 Invitation"]) or "")
        out["R2 Invitation"] = out["R2 Invitation"] or ("" if not out["R2 Total"] else normalize_decision(out["R2 Invitation"]) or "")
        out["Total points from Reviewer 1"] = _num_or_blank(get_value(row, summary_r1, out["R1 Total"]) or out["R1 Total"])
        out["Total points from Reviewer 2"] = _num_or_blank(get_value(row, summary_r2, out["R2 Total"]) or out["R2 Total"])
        both = get_value(row, summary_both, "")
        if not both:
            both = (float(out["R1 Total"] or 0) + float(out["R2 Total"] or 0)) if (out["R1 Total"] or out["R2 Total"]) else ""
        out["Total points from both reviewers"] = _num_or_blank(both)
        derived = derive_first_review_result(out["R1 Invitation"], out["R2 Invitation"])
        out["Derived First Review Result"] = derived
        out["Interview Required"] = interview_required_from_result(derived) if derived else ""
        for out_col, src_col in interview_map.items():
            out[out_col] = get_value(row, src_col)
        rows.append(out)
    result = pd.DataFrame(rows)
    return make_streamlit_safe_df(result)

def make_streamlit_safe_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else str(x))
    return out

def find_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["name_key"] = d["Full Name"].map(normalize_text)
    d["email_key"] = d["Email"].map(normalize_text)
    mask = d.duplicated("email_key", keep=False) & (d["email_key"] != "")
    mask |= d.duplicated("name_key", keep=False) & (d["name_key"] != "")
    cols = ["Applicant ID", "Full Name", "Email", "Country of Residence", "University", "Reviewer 1", "Reviewer 2"]
    return d.loc[mask, cols].sort_values(["Email", "Full Name"])

def update_candidate(df: pd.DataFrame, applicant_id: int, updates: dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    mask = out["Applicant ID"].astype(str) == str(applicant_id)
    for k, v in updates.items():
        if k not in out.columns:
            out[k] = ""
        out.loc[mask, k] = v
    if mask.any():
        idx = out.index[mask][0]
        r1 = out.at[idx, "R1 Invitation"]
        r2 = out.at[idx, "R2 Invitation"]
        derived = derive_first_review_result(r1, r2)
        out.at[idx, "Derived First Review Result"] = derived
        out.at[idx, "Interview Required"] = interview_required_from_result(derived) if derived else ""
        try:
            out.at[idx, "Total points from both reviewers"] = float(out.at[idx, "R1 Total"] or 0) + float(out.at[idx, "R2 Total"] or 0)
        except Exception:
            pass
    return make_streamlit_safe_df(out)

def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe_name = re.sub(r"[\\/*?:\[\]]", "", name)[:31] or "Sheet"
            make_streamlit_safe_df(df).to_excel(writer, sheet_name=safe_name, index=False)
    output.seek(0)
    return output.getvalue()
