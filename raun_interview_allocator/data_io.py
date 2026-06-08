import io
import re
import warnings
from datetime import date
from typing import Dict, List, Union

import pandas as pd

# Excel files exported from Google/Excel can contain unsupported UI extensions
# such as slicers, filters, or styling metadata. openpyxl can still read the
# data, but it emits noisy warnings. Suppress those for a clean deployment log.
warnings.filterwarnings(
    "ignore",
    message="Unknown extension is not supported and will be removed",
    category=UserWarning,
    module="openpyxl",
)


def safe_text(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip()


def sanitize_filename(text: str) -> str:
    text = re.sub(r"\s+", " ", safe_text(text))
    text = re.sub(r"[^\w\-. ]+", "", text, flags=re.UNICODE)
    return text.replace(" ", "_")


COLUMN_ALIASES: Dict[str, str] = {
    " Country of citizenship": "Country of citizenship",
    "Country of citizenship (If more than one, add below)": "Country of citizenship",
    "Country of citizenship (If more than one, add below) ": "Country of citizenship",
    "Last Name(s)": "Surname",
    "Last name(s)": "Surname",
    "Surname": "Surname",
    "University/Institution": "University",
    "University of current enrolment (If more than one affiliation, please add below)": "University",
    "University of current enrolment (If more than one affiliation, please add below)": "University",
    "University of current enrolment": "University",
    "Current level of study (or equivalent)": "Current level of study",
    "Field of study (If more than one, please add below)": "Major/Field",
    "Field of study": "Major/Field",
    "Would you like to apply for a scholarship (tuition waiver)?": "Applied for scholarship?",
    "Would you like to apply for a scholarship (tuition waiver)? (Please apply only if you have NO other means to finance your participation)": "Applied for scholarship?",
    "Would you still be willing to participate in the Academy if you do NOT receive the scholarship?": "Would still participate without scholarship?",
    "Do you have any accessibility requirements or special needs that we should be aware of to support your participation in the RAUN programme?": "Accessibility requirements?",
    "If yes, please briefly describe your requirements": "Accessibility details",
    "Current professional status": "Current professional status",
    "Current professional status ": "Current professional status",
    "Please briefly explain your motivation for applying under the Graduate Track and how you believe your experience adds value to the cohort.": "Graduate Track motivation",
    "Please briefly explain your motivation for applying under the Graduate Track and how you believe your experience adds value to the cohort. ": "Graduate Track motivation",
    "Have you previously applied to the RAUN programme?": "Previously applied to RAUN?",
    "Have you previously applied to the RAUN programme? ": "Previously applied to RAUN?",
    "If yes, in which year(s) did you previously apply?": "Previous application years",
    "If yes, in which year(s) did you previously apply? ": "Previous application years",
    "If yes, were you invited to an interview during your previous application?": "Previous interview invitation?",
    "If yes, were you invited to an interview during your previous application? ": "Previous interview invitation?",
    "Highest degree completed": "Highest degree completed",
    "Year of graduation (DD-MM-YYYY)": "Year of graduation",
    "E-Mail": "E-Mail",
    "Email": "E-Mail",
    "Email (We will use this email address for further communication)": "E-Mail",
    "Phone number with country code (example: +34123456789)": "Phone number with country code",
    "MA/PHD": "MA/PHD",
    "Please upload your PDF (as specified above) here.": "Application PDF Link",
}


def _bool_from_text(v, default=False):
    if pd.isna(v):
        return default
    s = str(v).strip().lower()
    if s in {"true", "yes", "y", "1", "x"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return default


def _canonical_col_name(name: str) -> str:
    """Normalize messy Google Forms/Excel headings for robust matching."""
    text = safe_text(name).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [safe_text(c).replace("\u00a0", " ").strip() for c in df.columns]

    canonical_aliases = {_canonical_col_name(k): v for k, v in COLUMN_ALIASES.items()}
    rename = {}
    for col in df.columns:
        clean = re.sub(r"\s+", " ", safe_text(col).replace("\u00a0", " ")).strip()
        key = _canonical_col_name(clean)
        if key in canonical_aliases:
            rename[col] = canonical_aliases[key]
            continue

        # Broad pattern matches for Google Forms headings that may include notes/new lines.
        if key.startswith("country of citizenship") and "second" not in key and "third" not in key:
            rename[col] = "Country of citizenship"
        elif key.startswith("email"):
            rename[col] = "E-Mail"
        elif key.startswith("phone number with country code"):
            rename[col] = "Phone number with country code"
        elif key.startswith("would you like to apply for a scholarship"):
            rename[col] = "Applied for scholarship?"
        elif key.startswith("would you still be willing to participate"):
            rename[col] = "Would still participate without scholarship?"
        elif key.startswith("please briefly explain your motivation for applying under the graduate track"):
            rename[col] = "Graduate Track motivation"
        elif key.startswith("have you previously applied to the raun programme"):
            rename[col] = "Previously applied to RAUN?"
        elif key.startswith("if yes, in which year"):
            rename[col] = "Previous application years"
        elif key.startswith("if yes, were you invited to an interview"):
            rename[col] = "Previous interview invitation?"
        elif key.startswith("do you have any accessibility requirements"):
            rename[col] = "Accessibility requirements?"
        elif key.startswith("if yes, please briefly describe your requirements"):
            rename[col] = "Accessibility details"
        elif key.startswith("university of current enrolment"):
            rename[col] = "University"
        elif key.startswith("field of study") and "2nd" not in key and "3rd" not in key:
            rename[col] = "Major/Field"
        elif key == "last name(s)" or key == "last name":
            rename[col] = "Surname"

    return df.rename(columns=rename)


def _combine_nonempty(row: pd.Series, cols: List[str]) -> str:
    parts = [safe_text(row.get(c)) for c in cols if safe_text(row.get(c))]
    return " | ".join(parts)


def _standardize_program(value: str) -> str:
    v = safe_text(value)
    low = v.lower()
    if "recent graduate" in low or "graduate track" in low:
        return "Graduate Track"
    if low in {"ma", "m.a.", "master", "masters", "master's", "msc", "m.sc."} or "master" in low:
        return "Master"
    if low in {"phd", "ph.d.", "doctoral", "doctorate"} or "phd" in low or "ph.d" in low or "doctor" in low:
        return "PhD"
    if "bachelor" in low or low in {"ba", "b.a.", "bsc", "b.sc."}:
        return "Bachelor"
    return v


def _normalize_applicant_df(df: pd.DataFrame) -> pd.DataFrame:
    df = _rename_columns(df)

    needed = [
        "First name(s)", "Middle name(s)", "Surname", "Gender", "Date of birth", "Age",
        "Country of residence", "Country of citizenship", "E-Mail", "Phone number with country code",
        "Are you currently enrolled in a Master or PhD program?", "MA/PHD", "Current level of study", "University",
        "University (Second affiliation, if applicable)", "University (Third affiliation, if applicable)",
        "Major/Field", "Field of study (2nd field of study, if applicable)", "Field of study (3rd field of study, if applicable)",
        "Area 1", "Area 2", "Area 3", "Applied for scholarship?",
        "Would still participate without scholarship?", "Accessibility requirements?", "Accessibility details",
        "Current professional status", "Graduate Track motivation", "Previously applied to RAUN?",
        "Previous application years", "Previous interview invitation?", "Highest degree completed", "Year of graduation",
        "Shortlisted", "Interview Required",
    ]
    for col in needed:
        if col not in df.columns:
            df[col] = ""

    df["Full Name"] = (
        df["First name(s)"].fillna("").astype(str) + " " +
        df["Middle name(s)"].fillna("").astype(str) + " " +
        df["Surname"].fillna("").astype(str)
    ).str.replace(r"\s+", " ", regex=True).str.strip()

    # If a file already has Full Name but split-name columns are blank, keep it.
    if "Full Name" in df.columns:
        supplied_name = df["Full Name"].fillna("").astype(str).str.strip()
        df["Full Name"] = df["Full Name"].where(df["Full Name"].astype(str).str.strip() != "", supplied_name)

    # The 2026-2027 Google Forms export no longer includes a direct Age column.
    # Compute age from Date of birth when Age is missing/blank.
    if df["Age"].fillna("").astype(str).str.strip().eq("").all() and "Date of birth" in df.columns:
        dob = pd.to_datetime(df["Date of birth"], errors="coerce", dayfirst=False)
        today = pd.Timestamp(date.today())
        df["Age"] = ((today - dob).dt.days / 365.25).apply(lambda x: int(x) if pd.notna(x) else "")

    enrolled = df["Are you currently enrolled in a Master or PhD program?"].fillna("").astype(str).str.strip()
    current_level = df["Current level of study"].fillna("").astype(str).str.strip()
    ma_phd = df["MA/PHD"].fillna("").astype(str).str.strip()
    highest = df["Highest degree completed"].fillna("").astype(str).str.strip()

    program = ma_phd.where(ma_phd != "", current_level)
    graduate_track_mask = enrolled.str.contains("graduate track", case=False, na=False) | current_level.str.contains("graduate track", case=False, na=False)
    program = program.where(program != "", highest)
    program = program.where(program != "", enrolled)
    program = program.replace({"I applied and I am waiting for the acceptance": "Pending acceptance"})
    df["Graduate Track Applicant?"] = graduate_track_mask.map({True: "Yes", False: "No"})
    df["Program"] = program.astype(str).map(_standardize_program)

    df["Email"] = df["E-Mail"].fillna("").astype(str).str.strip()
    df["Country of Residence"] = df["Country of residence"].fillna("").astype(str).str.strip()
    df["Country of Citizenship"] = df["Country of citizenship"].fillna("").astype(str).str.strip()
    df["Country of Citizenship (All)"] = df.apply(
        lambda r: _combine_nonempty(r, [
            "Country of citizenship",
            "Country of citizenship (Second, if applicable)",
            "Country of citizenship (Third, if applicable)",
        ]),
        axis=1,
    ) if "Country of citizenship (Second, if applicable)" in df.columns else df["Country of Citizenship"]

    df["Field"] = df["Major/Field"].fillna("").astype(str).str.strip()
    df["Field (All)"] = df.apply(
        lambda r: _combine_nonempty(r, [
            "Major/Field",
            "Field of study (2nd field of study, if applicable)",
            "Field of study (3rd field of study, if applicable)",
        ]),
        axis=1,
    )
    df["University"] = df["University"].fillna("").astype(str).str.strip()
    df["University (All)"] = df.apply(
        lambda r: _combine_nonempty(r, [
            "University",
            "University (Second affiliation, if applicable)",
            "University (Third affiliation, if applicable)",
        ]),
        axis=1,
    )

    for col in [
        "Applied for scholarship?", "Would still participate without scholarship?", "Accessibility requirements?",
        "Accessibility details", "Current professional status", "Previously applied to RAUN?",
        "Previous application years", "Previous interview invitation?", "Highest degree completed", "Year of graduation",
        "Gender", "Age", "Shortlisted", "Interview Required",
    ]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["University Background Tags"] = (
        df["Field"].fillna("").astype(str).str.strip() + ", " +
        df["Field (All)"].fillna("").astype(str).str.strip() + ", " +
        df["Area 1"].fillna("").astype(str).str.strip() + ", " +
        df["Area 2"].fillna("").astype(str).str.strip() + ", " +
        df["Area 3"].fillna("").astype(str).str.strip()
    ).str.strip(", ").str.replace(r",\s*,", ",", regex=True)
    df["Background Tags"] = df["University Background Tags"]

    keep_cols = [
        "Applicant ID", "Full Name", "Program", "University", "University (All)", "Field", "Field (All)", "Gender", "Age",
        "Country of Residence", "Country of Citizenship", "Country of Citizenship (All)", "Email",
        "Applied for scholarship?", "Would still participate without scholarship?",
        "Accessibility requirements?", "Accessibility details", "Graduate Track Applicant?", "Current professional status",
        "Highest degree completed", "Year of graduation", "Previously applied to RAUN?", "Previous application years",
        "Previous interview invitation?", "University Background Tags", "Background Tags", "Interview Required", "Shortlisted",
    ]
    if "Applicant ID" not in df.columns:
        df["Applicant ID"] = range(1, len(df) + 1)
    for c in keep_cols:
        if c not in df.columns:
            df[c] = ""

    out = df[keep_cols].copy()
    out = out[out["Full Name"].astype(str).str.strip() != ""].reset_index(drop=True)

    # Streamlit renders tables through Arrow. Keep IDs numeric and text fields
    # consistently string-based to avoid mixed object-column warnings such as
    # "Expected bytes, got int" during st.dataframe/st.data_editor rendering.
    out["Applicant ID"] = range(1, len(out) + 1)
    out["Applicant ID"] = pd.to_numeric(out["Applicant ID"], errors="coerce").fillna(0).astype(int)
    for col in out.columns:
        if col != "Applicant ID":
            out[col] = out[col].fillna("").astype(str)
    return out


def _try_normalize_from_header(df: pd.DataFrame, header_row: int) -> pd.DataFrame:
    raw = df.copy()
    if header_row >= len(raw):
        return pd.DataFrame()
    headers = [safe_text(x) for x in raw.iloc[header_row].tolist()]
    body = raw.iloc[header_row + 1:].copy()
    body.columns = headers
    body = body.loc[:, [c != "" for c in body.columns]]
    return _normalize_applicant_df(body)


def load_applicants(source: Union[pd.DataFrame, object]) -> pd.DataFrame:
    """Load applicants from uploaded Excel/CSV or a raw DataFrame from Google Sheets."""
    if isinstance(source, pd.DataFrame):
        attempts = []
        try:
            attempts.append(_normalize_applicant_df(source))
        except Exception:
            pass
        for header in [2, 1, 0]:
            try:
                attempts.append(_try_normalize_from_header(source, header))
            except Exception:
                pass
        for norm in attempts:
            if norm is not None and not norm.empty and norm["Full Name"].astype(str).str.strip().ne("").any():
                return norm
        return pd.DataFrame()

    name = safe_text(getattr(source, "name", "")).lower()
    if name.endswith(".csv"):
        if hasattr(source, "seek"):
            source.seek(0)
        df = pd.read_csv(source)
        return _normalize_applicant_df(df)

    attempts = [2, 1, 0]
    for header in attempts:
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            df = pd.read_excel(source, header=header)
            norm = _normalize_applicant_df(df)
            if not norm.empty and norm["Full Name"].astype(str).str.strip().ne("").any():
                return norm
        except Exception:
            continue
    if hasattr(source, "seek"):
        source.seek(0)
    df = pd.read_excel(source)
    return _normalize_applicant_df(df)


def normalize_reviewers_input(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [safe_text(c) for c in df.columns]

    rename_map = {
        "Reviewer": "Reviewer Name",
        "Name": "Reviewer Name",
        "Flex Limit": "Preselection Flex Limit",
        "Preselection Flexible?": "Preselection Flexible",
        "Flexible": "Preselection Flexible",
        "Flexibility": "Preselection Flexible",
    }
    df = df.rename(columns=rename_map)

    # Safety for old reviewer files: if an old column is named Interview Capacity but
    # this preselection app has no Preselection Capacity column, treat it as the
    # preselection availability number. This prevents the app from falling back to
    # uniform/default values and over-assigning reviewers.
    if "Preselection Capacity" not in df.columns and "Interview Capacity" in df.columns:
        df = df.rename(columns={"Interview Capacity": "Preselection Capacity"})

    needed = {
        "Reviewer Name": "",
        "Active": True,
        "Preselection Capacity": 0,
        "Preselection Flexible": False,
        "Preselection Flex Limit": 0,
        "Background Tags": "",
        "Reviewer Notes": "",
    }
    for k, v in needed.items():
        if k not in df.columns:
            df[k] = v

    df["Reviewer Name"] = df["Reviewer Name"].fillna("").astype(str).str.strip()
    df = df[df["Reviewer Name"] != ""].copy()

    df["Active"] = df["Active"].apply(lambda x: _bool_from_text(x, True))
    df["Preselection Flexible"] = df["Preselection Flexible"].apply(lambda x: _bool_from_text(x, False))
    df["Preselection Capacity"] = pd.to_numeric(df["Preselection Capacity"], errors="coerce").fillna(0).astype(int).clip(lower=0)
    df["Preselection Flex Limit"] = pd.to_numeric(df["Preselection Flex Limit"], errors="coerce").fillna(0).astype(int).clip(lower=0)

    # Strict interpretation:
    # - If flexible is FALSE, the total allowed load is exactly Preselection Capacity.
    # - If flexible is TRUE, Flex Limit is the strict total maximum, but cannot be
    #   lower than base capacity.
    df.loc[~df["Preselection Flexible"], "Preselection Flex Limit"] = df.loc[~df["Preselection Flexible"], "Preselection Capacity"]
    df.loc[df["Preselection Flexible"], "Preselection Flex Limit"] = df.loc[df["Preselection Flexible"], ["Preselection Flex Limit", "Preselection Capacity"]].max(axis=1)

    # If a reviewer is inactive, make the displayed limits zero so the dashboard and
    # plots are visually honest. The allocator also excludes inactive reviewers.
    df.loc[~df["Active"], ["Preselection Capacity", "Preselection Flex Limit"]] = 0

    df["Background Tags"] = df["Background Tags"].fillna("").astype(str)
    df["Reviewer Notes"] = df["Reviewer Notes"].fillna("").astype(str)

    return df[[
        "Reviewer Name", "Active", "Preselection Capacity", "Preselection Flexible",
        "Preselection Flex Limit", "Background Tags", "Reviewer Notes",
    ]].reset_index(drop=True)



def make_streamlit_safe_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy that Streamlit can render without Arrow type warnings.

    This is for display/export previews only. It does not change allocator logic.
    It fixes mixed object columns caused by messy Excel/Google Sheet imports.
    """
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [safe_text(c) for c in out.columns]
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else str(x))
    return out


def to_excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            if df is None:
                df = pd.DataFrame()
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    output.seek(0)
    return output.getvalue()
