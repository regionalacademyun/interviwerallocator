import math
import random
import re
import unicodedata
from typing import Dict, List, Set, Tuple

import pandas as pd

from .data_io import safe_text

YES_VALUES = {"yes", "y", "true", "1", "x", "available", "ok"}
NO_VALUES = {"no", "n", "false", "0"}


def _normalize_name(name: str) -> str:
    return unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("utf-8").lower().strip()


def _norm_key(value) -> str:
    text = safe_text(value).replace("\xa0", " ").lower()
    return "".join(ch for ch in text if ch.isalnum())


def _cell_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def parse_tags(value) -> Set[str]:
    if pd.isna(value) or str(value).strip() == "":
        return set()
    return {x.strip().lower() for x in str(value).replace(";", ",").split(",") if x.strip()}


def parse_slots(value) -> Set[str]:
    if pd.isna(value) or str(value).strip() == "":
        return set()
    raw = str(value).replace("\n", ",").replace(";", ",").replace("|", ",")
    return {x.strip() for x in raw.split(",") if x.strip()}


def _as_yes_no_maybe(value) -> str:
    s = _cell_text(value).lower()
    if not s:
        return ""
    if s in {"yes", "y", "true", "1", "invite", "invited", "call", "shortlisted", "selected"}:
        return "Yes"
    if s in {"no", "n", "false", "0", "reject", "rejected", "not invited", "not invite"}:
        return "No"
    if "maybe" in s:
        return "Maybe"
    if "yes" in s or "invite" in s or "interview" in s or "call" in s:
        return "Yes"
    if "no" in s or "reject" in s or "not" in s:
        return "No"
    return _cell_text(value)


def derive_first_review_result(r1_decision, r2_decision) -> str:
    r1 = _as_yes_no_maybe(r1_decision)
    r2 = _as_yes_no_maybe(r2_decision)
    if r1 == "Yes" and r2 == "Yes":
        return "Yes"
    if r1 == "No" and r2 == "No":
        return "No"
    if r1 == "Maybe" and r2 == "Maybe":
        return "Maybe"
    if {r1, r2} == {"Maybe", "Yes"}:
        return "Maybe+Yes"
    if r1 or r2:
        return "Maybe+No"
    return "No decision yet"


def decision_to_interview(value, policy: str = "Exclude only explicit No+No") -> bool:
    """Return whether a candidate should enter the interview allocation pool.

    Default RAUN operational rule for this app:
    everyone remains in the interview-allocation pool unless the combined
    first-review decision is explicitly No. This avoids accidentally excluding
    candidates while Reviewer 1/2 decisions are still incomplete.
    """
    s_raw = _cell_text(value)
    s = s_raw.lower().replace(" ", "")
    if policy == "Exclude only explicit No+No":
        return s not in {"no", "n", "false", "0"}
    if policy == "Exclude No and No decision yet":
        return s not in {"no", "n", "false", "0", "nodecisionyet", "", "nan"}
    if policy == "Yes only":
        return s in {"yes", "y", "true", "1"}
    if policy == "Yes + Maybe+Yes + Maybe":
        return s in {"yes", "y", "true", "1", "maybe+yes", "maybeyes", "maybe"}
    return s in {"yes", "y", "true", "1", "maybe+yes", "maybeyes"}


def _find_header_row(raw_df: pd.DataFrame) -> int:
    raw = raw_df.copy()
    best_idx, best_score = 0, -1
    for idx in range(min(15, len(raw))):
        vals = [_cell_text(v) for v in raw.iloc[idx].tolist()]
        keys = [_norm_key(v) for v in vals]
        score = 0
        if "firstnames" in keys or "firstname" in keys:
            score += 20
        if "surname" in keys or "lastname" in keys or "lastnames" in keys:
            score += 15
        if "reviewer1" in keys:
            score += 15
        if "reviewer2" in keys:
            score += 15
        if any("invitationtointerview" in k for k in keys):
            score += 25
        if any("totalpointsfromreviewer1" in k for k in keys):
            score += 20
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx


def _make_unique_headers(headers: List[str]) -> List[str]:
    seen = {}
    out = []
    for i, h in enumerate(headers):
        h = _cell_text(h) or f"Unnamed_{i+1}"
        if h in seen:
            seen[h] += 1
            h = f"{h}__{seen[h]+1}"
        else:
            seen[h] = 0
        out.append(h)
    return out


def raw_to_header_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()
    header_row = _find_header_row(raw_df)
    headers = _make_unique_headers(raw_df.iloc[header_row].tolist())
    body = raw_df.iloc[header_row + 1:].copy()
    body.columns = headers
    body = body.dropna(axis=0, how="all").reset_index(drop=True)
    return body


def _find_col(df: pd.DataFrame, wanted_keys: List[str], start_at: int | None = None, exclude_keys: List[str] | None = None):
    exclude_keys = exclude_keys or []
    for i, col in enumerate(df.columns):
        if start_at is not None and i < start_at:
            continue
        key = _norm_key(col)
        if any(ex in key for ex in exclude_keys):
            continue
        if any(w in key for w in wanted_keys):
            return col
    return None


def _find_cols(df: pd.DataFrame, wanted_keys: List[str], start_at: int | None = None):
    out = []
    for i, col in enumerate(df.columns):
        if start_at is not None and i < start_at:
            continue
        key = _norm_key(col)
        if any(w in key for w in wanted_keys):
            out.append(col)
    return out


def parse_interview_source(raw_df: pd.DataFrame, decision_policy: str = "Yes + Maybe+Yes") -> pd.DataFrame:
    """Parse the RAUN interview-allocation input sheet.

    Operational format:
    - The real header row is around Excel row 2 and data starts from row 3.
    - First columns contain Reviewer 1, Reviewer 2 and applicant details.
    - The preselection scoring block contains two repeated reviewer assessments.
    - The two `Invitation to interview?` columns are used to derive the first-review result.
    """
    df = raw_to_header_df(raw_df)
    if df.empty:
        return pd.DataFrame()

    # Scoring starts after application/accessibility fields. Use the first assessment criterion as anchor if found.
    scoring_start = 0
    for i, col in enumerate(df.columns):
        if "researchacademicexperience" in _norm_key(col):
            scoring_start = i
            break

    id_col = _find_col(df, ["applicantid", "applicationid", "candidateid", "number", "no"], exclude_keys=["phonenumber"])
    hash_col = _find_col(df, ["#"])
    if id_col is None and hash_col is not None:
        id_col = hash_col
    r1_col = _find_col(df, ["reviewer1"], exclude_keys=["totalpointsfromreviewer1"])
    r2_col = _find_col(df, ["reviewer2"], exclude_keys=["totalpointsfromreviewer2"])
    first_col = _find_col(df, ["firstnames", "firstname", "givenname"])
    middle_col = _find_col(df, ["middlenames", "middlename"])
    last_col = _find_col(df, ["surname", "lastname", "lastnames", "familyname"])
    email_col = _find_col(df, ["email", "emailaddress"])
    program_col = _find_col(df, ["maphd", "currentlevelofstudy", "program", "programme"])
    university_col = _find_col(df, ["university", "universityofcurrentenrolment"])
    field_col = _find_col(df, ["majorfield", "fieldofstudy"])
    tag_cols = [_find_col(df, ["area1"]), _find_col(df, ["area2"]), _find_col(df, ["area3"]), field_col]
    tag_cols = [c for c in tag_cols if c]

    invitation_cols = _find_cols(df, ["invitationtointerview", "invitetointerview"], start_at=scoring_start)
    total_point_cols = _find_cols(df, ["totalpoints"], start_at=scoring_start)
    # First two total points in scoring block are reviewer totals. Later totals may be combined.
    r1_total_col = total_point_cols[0] if len(total_point_cols) >= 1 else None
    r2_total_col = total_point_cols[1] if len(total_point_cols) >= 2 else None
    both_total_col = _find_col(df, ["totalpointsfrombothreviewers"], start_at=scoring_start)
    if both_total_col is None:
        # Often it is the last total-points column in the pre-interview block.
        both_total_col = total_point_cols[-1] if len(total_point_cols) >= 3 else None

    r1_inv = df[invitation_cols[0]].fillna("").astype(str).str.strip() if len(invitation_cols) >= 1 else pd.Series([""] * len(df), index=df.index)
    r2_inv = df[invitation_cols[1]].fillna("").astype(str).str.strip() if len(invitation_cols) >= 2 else pd.Series([""] * len(df), index=df.index)
    final_result = pd.Series([derive_first_review_result(a, b) for a, b in zip(r1_inv, r2_inv)], index=df.index)

    if id_col:
        ids = pd.to_numeric(df[id_col], errors="coerce")
        fallback = pd.Series(range(1, len(df)+1), index=df.index)
        applicant_ids = ids.fillna(fallback).astype(int)
    else:
        applicant_ids = range(1, len(df)+1)

    first = df[first_col].fillna("").astype(str) if first_col else ""
    middle = df[middle_col].fillna("").astype(str) if middle_col else ""
    last = df[last_col].fillna("").astype(str) if last_col else ""
    if hasattr(first, "str") and hasattr(last, "str"):
        full_name = (first + " " + (middle if hasattr(middle, "str") else "") + " " + last).str.replace(r"\s+", " ", regex=True).str.strip()
    else:
        full_name = pd.Series([""] * len(df), index=df.index)

    def build_tags(row):
        vals = [safe_text(row.get(c)) for c in tag_cols if safe_text(row.get(c))]
        return ", ".join(vals)

    out = pd.DataFrame({
        "Applicant ID": applicant_ids,
        "Full Name": full_name,
        "Email": df[email_col].fillna("").astype(str).str.strip() if email_col else "",
        "Program": df[program_col].fillna("").astype(str).str.strip() if program_col else "",
        "University": df[university_col].fillna("").astype(str).str.strip() if university_col else "",
        "Field": df[field_col].fillna("").astype(str).str.strip() if field_col else "",
        "Preselection Reviewer 1": df[r1_col].fillna("").astype(str).str.strip() if r1_col else "",
        "Preselection Reviewer 2": df[r2_col].fillna("").astype(str).str.strip() if r2_col else "",
        "Reviewer 1 Invitation": r1_inv,
        "Reviewer 2 Invitation": r2_inv,
        "Final Result- First review": final_result,
        "Interview Required": final_result.map(lambda x: "Yes" if decision_to_interview(x, decision_policy) else "No"),
        "Decision Policy Used": decision_policy,
        "Total points from Reviewer 1": df[r1_total_col].fillna("").astype(str).str.strip() if r1_total_col else "",
        "Total points from Reviewer 2": df[r2_total_col].fillna("").astype(str).str.strip() if r2_total_col else "",
        "Total points from both reviewers": df[both_total_col].fillna("").astype(str).str.strip() if both_total_col else "",
        "Background Tags": df.apply(build_tags, axis=1),
    })
    out = out[out["Full Name"].astype(str).str.strip().ne("")].copy()
    for c in out.columns:
        if c != "Applicant ID":
            out[c] = out[c].fillna("").astype(str)
    return out.reset_index(drop=True)


def filter_interview_pool(parsed_df: pd.DataFrame) -> pd.DataFrame:
    if parsed_df is None or parsed_df.empty:
        return pd.DataFrame()
    return parsed_df[parsed_df["Interview Required"].astype(str).str.lower().eq("yes")].copy().reset_index(drop=True)


def build_default_interviewers_df(team_members: List[str], interview_pool_df: pd.DataFrame | None = None, use_uniform_baseline: bool = False) -> pd.DataFrame:
    tag_map = {
        "Laura María García": "economics, management, organization, industrial engineering, data analysis, education, public policy, mental health, public health, quantitative research",
        "Thi Hoang": "human trafficking, anti-human trafficking, organized crime, technology, cybercrime, migration, forced labour, modern slavery, child protection, crime policy, digital governance, criminal justice",
        "Roman Hoffmann": "economics, sociology, development, poverty, health, environment, climate change, migration, livelihoods, refugees, policy interventions, vulnerability, adaptation",
        "Mariia Kostetckaia (Masha)": "sustainability, sustainable development, european union, international relations, global studies, asylum, refugees, migration, policy",
        "Samar Momin": "engineering, earthquake engineering, structural dynamics, disaster risk reduction, resilience, seismic risk, public health, contaminated medicines, regulation, data analysis, infrastructure, risk assessment",
        "Vanessa Moser": "international relations, united nations, policy, governance, youth engagement, sustainable development, research, programme coordination",
        "Florian Müller": "economics, business, international management, renewable energy, energy policy, public investment, management",
        "Ivy Omondi": "peace and security, conflict, refugees, gender, lgbtq, trafficking in persons, diplomacy, victim-centred approach",
        "Isabel Sáenz Hernández": "sociology, migration, multilingualism, education, inequality, immigrant background, language, inclusion, accessibility, digital inequality, social demography, human rights",
        "Berkay Öztürk": "migration, diaspora, remittances, identity, policy, global governance, youth inclusion, security, international relations, civil society, refugee participation, sport",
        "Martina Pardy": "economics, economic geography, inequality, globalization, regional development, migration, women’s participation, electoral reform, governance",
        "Mary Peloche": "law, political science, refugee protection, migration policy, national security, public administration, international relations, governance",
        "Nicola Jansen": "law",
        "Cecilia Vera Lagomarsino": "international relations, media freedom, osce, migration, migration law, gender equality, elections, democratic governance, european affairs, human rights",
        "Billy Batware": "transnational organized crime, unodc, international security, conflict analysis, development, human rights, sustainable development, youth empowerment, education, leadership, diplomacy, international relations",
    }
    members = sorted([safe_text(x) for x in team_members if safe_text(x)], key=_normalize_name)
    df = pd.DataFrame({"Reviewer Name": members})
    df["Active"] = True
    if use_uniform_baseline and interview_pool_df is not None and len(interview_pool_df) > 0 and len(df) > 0:
        demand = len(interview_pool_df)
        base = demand // len(df)
        rem = demand % len(df)
        df["Interview Capacity"] = base
        if rem > 0:
            df.loc[df.index[:rem], "Interview Capacity"] += 1
    else:
        df["Interview Capacity"] = 5
    df["Available Slots"] = ""
    df["Background Tags"] = df["Reviewer Name"].map(tag_map).fillna("")
    df["Reviewer Notes"] = ""
    return df[["Reviewer Name", "Active", "Interview Capacity", "Available Slots", "Background Tags", "Reviewer Notes"]]


def _bool_from_text(v, default=False):
    s = str(v or "").strip().lower()
    if s in {"true", "yes", "y", "1", "x"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return default


def normalize_interviewers_input(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [safe_text(c) for c in df.columns]
    rename_map = {
        "Reviewer": "Reviewer Name",
        "Name": "Reviewer Name",
        "Interviewer": "Reviewer Name",
        "Capacity": "Interview Capacity",
        "Can Interview": "Active",
        "Availability": "Available Slots",
        "Available": "Available Slots",
        "Slots": "Available Slots",
    }
    df = df.rename(columns=rename_map)
    needed = {"Reviewer Name": "", "Active": True, "Interview Capacity": 0, "Available Slots": "", "Background Tags": "", "Reviewer Notes": ""}
    for k, v in needed.items():
        if k not in df.columns:
            df[k] = v
    df["Reviewer Name"] = df["Reviewer Name"].fillna("").astype(str).str.strip().map(_canonical_reviewer_display)
    df = df[df["Reviewer Name"].ne("")].copy()
    df["Active"] = df["Active"].apply(lambda x: _bool_from_text(x, True))
    df["Interview Capacity"] = pd.to_numeric(df["Interview Capacity"], errors="coerce").fillna(0).astype(int).clip(lower=0)
    df.loc[~df["Active"], "Interview Capacity"] = 0
    df["Available Slots"] = df["Available Slots"].fillna("").astype(str)
    df["Background Tags"] = df["Background Tags"].fillna("").astype(str)
    df["Reviewer Notes"] = df["Reviewer Notes"].fillna("").astype(str)
    return df[["Reviewer Name", "Active", "Interview Capacity", "Available Slots", "Background Tags", "Reviewer Notes"]].reset_index(drop=True)


def normalize_candidate_availability(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [safe_text(c) for c in df.columns]
    rename = {"Name": "Full Name", "Applicant Name": "Full Name", "Availability": "Available Slots", "Slots": "Available Slots"}
    df = df.rename(columns=rename)
    if "Applicant ID" not in df.columns:
        df["Applicant ID"] = ""
    if "Full Name" not in df.columns:
        df["Full Name"] = ""
    if "Available Slots" not in df.columns:
        id_cols = {"Applicant ID", "Full Name", "Email"}
        slot_cols = [c for c in df.columns if c not in id_cols]
        vals = []
        for _, row in df.iterrows():
            slots = []
            for c in slot_cols:
                if str(row.get(c, "")).strip().lower() in YES_VALUES:
                    slots.append(str(c))
            vals.append(", ".join(slots))
        df["Available Slots"] = vals
    df["Applicant ID"] = pd.to_numeric(df["Applicant ID"], errors="coerce")
    df["Full Name"] = df["Full Name"].fillna("").astype(str).str.strip()
    df["Available Slots"] = df["Available Slots"].fillna("").astype(str)
    return df[["Applicant ID", "Full Name", "Available Slots"]].reset_index(drop=True)


def compute_planning_metrics(interview_pool_df: pd.DataFrame, interviewers_df: pd.DataFrame) -> Dict[str, int]:
    """Planning numbers for the interview dashboard.

    The function is intentionally defensive because the dashboard may be called
    before the interviewer table has been fully initialized, or with a reviewer
    table adapted from the preselection layout during early preview.
    """
    if interview_pool_df is None:
        demand = 0
    else:
        demand = len(interview_pool_df)

    if interviewers_df is None or interviewers_df.empty:
        active = pd.DataFrame()
        capacity = 0
    else:
        active = interviewers_df[interviewers_df["Active"] == True].copy() if "Active" in interviewers_df.columns else interviewers_df.copy()

        if "Interview Capacity" in active.columns:
            capacity_series = active["Interview Capacity"]
        elif "Preselection Capacity" in active.columns:
            # Compatibility fallback only; normally the interview app uses
            # Interview Capacity. This prevents crashes if a table is adapted
            # from the preselection app structure.
            capacity_series = active["Preselection Capacity"]
        else:
            capacity_series = pd.Series([0] * len(active), index=active.index)

        capacity = int(pd.to_numeric(capacity_series, errors="coerce").fillna(0).sum()) if len(active) else 0

    return {
        "Applicants": demand,
        "Interview Candidates": demand,
        "Active Interviewers": len(active),
        "Interview Capacity": capacity,
        "Capacity Gap": capacity - demand,
        "Shortage": max(0, demand - capacity),
        "Suggested Avg Interviews per Interviewer": math.ceil(demand / len(active)) if len(active) else 0,
    }


def _availability_lookup(df: pd.DataFrame, by: str) -> Dict[str, Set[str]]:
    if df is None or df.empty:
        return {}
    lookup = {}
    for _, row in df.iterrows():
        key = safe_text(row.get(by))
        if key:
            lookup[key] = parse_slots(row.get("Available Slots", ""))
    return lookup


def _availability_lookup_id(df: pd.DataFrame) -> Dict[int, Set[str]]:
    if df is None or df.empty or "Applicant ID" not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        try:
            aid = int(row.get("Applicant ID"))
        except Exception:
            continue
        out[aid] = parse_slots(row.get("Available Slots", ""))
    return out


def _match_bonus(overlap: int, strength: str) -> float:
    if strength == "Off":
        return 0.0
    if strength == "Low":
        return overlap * 0.75
    return overlap * 1.5


def allocate_interviews(
    interview_pool_df: pd.DataFrame,
    interviewers_df: pd.DataFrame,
    candidate_availability_df: pd.DataFrame | None = None,
    seed: int = 42,
    match_strength: str = "Low",
    prefer_preselection_reviewer: bool = True,
    require_availability_overlap: bool = False,
):
    rng = random.Random(seed)
    pool = interview_pool_df.copy()

    interviewers = {}
    for _, row in interviewers_df.iterrows():
        if not bool(row.get("Active", True)):
            continue
        name = safe_text(row.get("Reviewer Name"))
        cap = int(row.get("Interview Capacity", 0)) if str(row.get("Interview Capacity", "")).strip() != "" else 0
        if not name or cap <= 0:
            continue
        interviewers[name] = {
            "capacity": cap,
            "assigned": 0,
            "tags": parse_tags(row.get("Background Tags", "")),
            "available_slots": parse_slots(row.get("Available Slots", "")),
        }

    c_av_id = _availability_lookup_id(candidate_availability_df) if candidate_availability_df is not None else {}
    c_av_name = _availability_lookup(candidate_availability_df, "Full Name") if candidate_availability_df is not None else {}

    results = []
    exceptions = []

    for _, row in pool.sample(frac=1, random_state=seed).reset_index(drop=True).iterrows():
        aid = int(row["Applicant ID"])
        full_name = safe_text(row.get("Full Name"))
        tags = parse_tags(row.get("Background Tags", ""))
        pre1 = safe_text(row.get("Preselection Reviewer 1"))
        pre2 = safe_text(row.get("Preselection Reviewer 2"))
        pre_reviewers = {x for x in [pre1, pre2] if x}
        pre_reviewer_keys = {_reviewer_match_key(x) for x in pre_reviewers}
        candidate_slots = c_av_id.get(aid, set()) or c_av_name.get(full_name, set())

        candidates: List[Tuple[str, float, str, bool, bool]] = []
        for name, rv in interviewers.items():
            if rv["assigned"] >= rv["capacity"]:
                continue
            overlap_slots = set()
            if candidate_slots and rv["available_slots"]:
                overlap_slots = candidate_slots.intersection(rv["available_slots"])
                if require_availability_overlap and not overlap_slots:
                    continue
            elif require_availability_overlap and (candidate_slots or rv["available_slots"]):
                continue
            continuity = _reviewer_match_key(name) in pre_reviewer_keys
            overlap = len(tags.intersection(rv["tags"]))
            load_ratio = rv["assigned"] / max(rv["capacity"], 1)
            score = rng.uniform(0, 0.1) - (load_ratio * 4.0) + _match_bonus(overlap, match_strength)
            if prefer_preselection_reviewer and continuity:
                score += 100.0
            slot = sorted(overlap_slots)[0] if overlap_slots else ""
            candidates.append((name, score, slot, continuity, bool(overlap_slots)))

        candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
        interviewer = ""
        proposed_slot = ""
        continuity_used = False
        availability_overlap = False
        if candidates:
            interviewer, _score, proposed_slot, continuity_used, availability_overlap = candidates[0]
            interviewers[interviewer]["assigned"] += 1
        else:
            exceptions.append({
                "Applicant ID": aid,
                "Full Name": full_name,
                "Issue Type": "Incomplete interview allocation",
                "Details": "No active interviewer with remaining capacity met the current constraints. Increase capacity or relax availability overlap.",
            })

        if interviewer and prefer_preselection_reviewer and not continuity_used:
            exceptions.append({
                "Applicant ID": aid,
                "Full Name": full_name,
                "Issue Type": "Continuity not possible",
                "Details": "Neither preselection reviewer was available within capacity/constraints, so another interviewer was assigned.",
            })
        if interviewer and candidate_slots and interviewers[interviewer]["available_slots"] and not availability_overlap:
            exceptions.append({
                "Applicant ID": aid,
                "Full Name": full_name,
                "Issue Type": "No availability overlap found",
                "Details": "Interviewer was assigned, but no shared availability slot was found. They should coordinate manually.",
            })

        results.append({
            "Applicant ID": aid,
            "Full Name": full_name,
            "Email": row.get("Email", ""),
            "Program": row.get("Program", ""),
            "University": row.get("University", ""),
            "Field": row.get("Field", ""),
            "Preselection Reviewer 1": pre1,
            "Preselection Reviewer 2": pre2,
            "Reviewer 1 Invitation": row.get("Reviewer 1 Invitation", ""),
            "Reviewer 2 Invitation": row.get("Reviewer 2 Invitation", ""),
            "Final Result- First review": row.get("Final Result- First review", ""),
            "Total points from Reviewer 1": row.get("Total points from Reviewer 1", ""),
            "Total points from Reviewer 2": row.get("Total points from Reviewer 2", ""),
            "Total points from both reviewers": row.get("Total points from both reviewers", ""),
            "Interview Reviewer": interviewer,
            "Continuity Used": "Yes" if continuity_used else "No",
            "Proposed Interview Slot": proposed_slot,
            "Availability Overlap Found": "Yes" if availability_overlap else "No",
            "Candidate Available Slots": ", ".join(sorted(candidate_slots)),
        })

    result_df = pd.DataFrame(results).sort_values("Applicant ID").reset_index(drop=True) if results else pd.DataFrame()
    load_rows = []
    for name, rv in interviewers.items():
        assigned = rv["assigned"]
        cap = rv["capacity"]
        load_rows.append({
            "Reviewer Name": name,
            "Interview Assigned": assigned,
            "Interview Capacity": cap,
            "Remaining Interview Capacity": cap - assigned,
            "Interview Utilization %": round((assigned / cap * 100), 1) if cap > 0 else 0,
        })
    loads_df = pd.DataFrame(load_rows).sort_values(["Interview Assigned", "Reviewer Name"], ascending=[False, True]).reset_index(drop=True) if load_rows else pd.DataFrame()
    return result_df, loads_df, pd.DataFrame(exceptions)
# =========================================================
# AVAILABILITY MATRIX PATCH
# =========================================================
# The functions below intentionally override earlier lightweight versions.
# They add support for the RAUN 2025/2026 availability matrix format:
# row 1 = dates, row 2 = times, rows below = people/candidates with Yes/No.

AVAILABILITY_YES_VALUES = {
    "yes", "y", "true", "1", "x", "available", "ok",
    "under reserve", "underreserve", "reserve", "reserved", "maybe"
}
AVAILABILITY_NO_VALUES = {"no", "n", "false", "0", "", "nan", "none"}


def _normalize_person_key(value) -> str:
    text = unicodedata.normalize("NFKD", safe_text(value)).encode("ascii", "ignore").decode("utf-8").lower().strip()
    return re.sub(r"\s+", " ", text)


def _person_match_key(value) -> str:
    """Compact matching key for candidate/reviewer names.

    This prevents small spacing, accent, and punctuation differences from
    breaking availability matching, e.g. double spaces or accented names.
    """
    return "".join(ch for ch in _normalize_person_key(value) if ch.isalnum())


REVIEWER_DISPLAY_ALIASES = {
    "masha": "Mariia Kostetckaia (Masha)",
    "mariiakostetckaiamasha": "Mariia Kostetckaia (Masha)",
    "billy": "Billy Batware",
    "billybatware": "Billy Batware",
    "ceci": "Cecilia Vera Lagomarsino",
    "cecilia": "Cecilia Vera Lagomarsino",
    "ceciliaveralagomarsino": "Cecilia Vera Lagomarsino",
    "isabelsaenz": "Isabel Sáenz Hernández",
    "isabelsaenzhernandez": "Isabel Sáenz Hernández",
    "mary": "Mary Peloche",
    "marypeloche": "Mary Peloche",
    "nicola": "Nicola Jansen",
    "nicolajansen": "Nicola Jansen",
    "thi": "Thi Hoang",
    "thihoang": "Thi Hoang",
    "martina": "Martina Pardy",
    "martinapardy": "Martina Pardy",
    "samar": "Samar Momin",
    "samarmomin": "Samar Momin",
    "vanessa": "Vanessa Moser",
    "vanessamoser": "Vanessa Moser",
}


def _canonical_reviewer_display(value) -> str:
    text = safe_text(value)
    return REVIEWER_DISPLAY_ALIASES.get(_person_match_key(text), text)


def _is_yes_available(value) -> bool:
    s = _cell_text(value).lower()
    if s in AVAILABILITY_YES_VALUES:
        return True
    if s in AVAILABILITY_NO_VALUES:
        return False
    # Be deliberately permissive for old sheets that say things like "Yes - under reserve".
    return "yes" in s or "available" in s or "reserve" in s


def _format_date_part(value) -> str:
    if pd.isna(value):
        return ""
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date().isoformat()
        except Exception:
            pass
    text = _cell_text(value)
    if not text:
        return ""
    dt = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.notna(dt):
        return dt.date().isoformat()
    return text


def _format_time_part(value) -> str:
    if pd.isna(value):
        return ""
    if hasattr(value, "strftime") and not isinstance(value, str):
        try:
            return value.strftime("%H:%M")
        except Exception:
            pass
    text = _cell_text(value)
    if not text:
        return ""
    dt = pd.to_datetime(text, errors="coerce")
    if pd.notna(dt):
        return dt.strftime("%H:%M")
    # Handle strings like 8:00 or 08:00:00 without a parsed date.
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return text


def _make_slot_label(date_value, time_value) -> str:
    d = _format_date_part(date_value)
    t = _format_time_part(time_value)
    if d and t:
        return f"{d} {t}"
    if d:
        return d
    return t


def _slot_sort_key(slot: str):
    dt = pd.to_datetime(slot, errors="coerce")
    if pd.notna(dt):
        return (0, dt)
    return (1, slot)


def parse_slots(value) -> Set[str]:
    """Parse slot strings into canonical slot labels.

    Supports comma/semicolon/newline separated text and preserves already
    canonical labels such as "2025-06-23 08:00".
    """
    if pd.isna(value) or str(value).strip() == "":
        return set()
    raw = str(value).replace("\n", ",").replace(";", ",").replace("|", ",")
    return {_cell_text(x) for x in raw.split(",") if _cell_text(x)}


def _looks_like_availability_matrix(raw_df: pd.DataFrame) -> bool:
    if raw_df is None or raw_df.empty or raw_df.shape[0] < 3 or raw_df.shape[1] < 4:
        return False
    row0 = raw_df.iloc[0].tolist()
    row1 = raw_df.iloc[1].tolist() if raw_df.shape[0] > 1 else []
    date_like = 0
    time_like = 0
    for v in row0[1: min(len(row0), 25)]:
        if _format_date_part(v):
            date_like += 1
    for v in row1[1: min(len(row1), 25)]:
        if _format_time_part(v):
            time_like += 1
    return date_like >= 3 and time_like >= 3


def _promote_header_if_needed(df: pd.DataFrame) -> pd.DataFrame:
    """Accept both normal headered files and header=None reads."""
    if df is None or df.empty:
        return pd.DataFrame()
    tmp = df.copy()
    tmp.columns = [safe_text(c) for c in tmp.columns]
    normalized_cols = {_norm_key(c) for c in tmp.columns}
    if {"reviewername", "interviewcapacity", "fullName"}.intersection(normalized_cols):
        return tmp
    # If first row contains clear headers, promote it.
    first_row_keys = {_norm_key(x) for x in tmp.iloc[0].tolist()}
    if {"reviewername", "interviewer", "interviewcapacity", "fullname", "availability", "availableslots"}.intersection(first_row_keys):
        headers = _make_unique_headers(tmp.iloc[0].tolist())
        body = tmp.iloc[1:].copy()
        body.columns = headers
        return body.reset_index(drop=True)
    return tmp


def _availability_matrix_to_rows(raw_df: pd.DataFrame, person_col_name: str) -> pd.DataFrame:
    raw = raw_df.copy()
    if not _looks_like_availability_matrix(raw):
        return pd.DataFrame()

    date_row = raw.iloc[0]
    time_row = raw.iloc[1]
    slot_columns: list[tuple[int, str]] = []
    for j in range(1, raw.shape[1]):
        slot = _make_slot_label(date_row.iloc[j], time_row.iloc[j])
        if slot:
            slot_columns.append((j, slot))

    rows = []
    for i in range(2, raw.shape[0]):
        name = _cell_text(raw.iloc[i, 0])
        if not name:
            continue
        # Stop obvious summary/sidebar rows.
        if name.lower() in {"name", "total", "conteo", "count"}:
            continue
        slots = []
        reserve_slots = []
        for j, slot in slot_columns:
            val = _cell_text(raw.iloc[i, j])
            if _is_yes_available(val):
                slots.append(slot)
                if "reserve" in val.lower():
                    reserve_slots.append(slot)
        rows.append({
            person_col_name: name,
            "Available Slots": ", ".join(slots),
            "Availability Slot Count": len(slots),
            "Under Reserve Slots": ", ".join(reserve_slots),
        })
    return pd.DataFrame(rows)


def normalize_interviewers_input(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize either a simple interviewer table or the RAUN team matrix.

    Matrix input example:
    - row 1: dates
    - row 2: times
    - rows below: interviewer names and Yes/No availability
    The interview capacity is automatically set to the number of available slots.
    """
    raw = df.copy()
    matrix = _availability_matrix_to_rows(raw, "Reviewer Name")
    if not matrix.empty:
        matrix["Reviewer Name"] = matrix["Reviewer Name"].map(_canonical_reviewer_display)
        matrix["Active"] = matrix["Availability Slot Count"].astype(int) > 0
        matrix["Interview Capacity"] = matrix["Availability Slot Count"].astype(int)
        matrix["Background Tags"] = ""
        matrix["Reviewer Notes"] = matrix.apply(
            lambda r: f"Loaded from availability matrix. Under reserve slots: {r.get('Under Reserve Slots','')}" if safe_text(r.get("Under Reserve Slots")) else "Loaded from availability matrix.",
            axis=1,
        )
        return matrix[["Reviewer Name", "Active", "Interview Capacity", "Available Slots", "Background Tags", "Reviewer Notes", "Availability Slot Count"]].reset_index(drop=True)

    df = _promote_header_if_needed(df.copy())
    df.columns = [safe_text(c) for c in df.columns]
    rename_map = {
        "Reviewer": "Reviewer Name",
        "Name": "Reviewer Name",
        "Interviewer": "Reviewer Name",
        "Interviewer Name": "Reviewer Name",
        "Capacity": "Interview Capacity",
        "Can Interview": "Active",
        "Availability": "Available Slots",
        "Available": "Available Slots",
        "Slots": "Available Slots",
    }
    df = df.rename(columns=rename_map)
    needed = {"Reviewer Name": "", "Active": True, "Interview Capacity": 0, "Available Slots": "", "Background Tags": "", "Reviewer Notes": ""}
    for k, v in needed.items():
        if k not in df.columns:
            df[k] = v
    df["Reviewer Name"] = df["Reviewer Name"].fillna("").astype(str).str.strip()
    df = df[df["Reviewer Name"].ne("")].copy()
    df["Active"] = df["Active"].apply(lambda x: _bool_from_text(x, True))
    # If capacity is missing/zero but slots are filled, derive capacity from slot count.
    slot_counts = df["Available Slots"].apply(lambda x: len(parse_slots(x)))
    df["Interview Capacity"] = pd.to_numeric(df["Interview Capacity"], errors="coerce").fillna(0).astype(int).clip(lower=0)
    df.loc[(df["Interview Capacity"] == 0) & (slot_counts > 0), "Interview Capacity"] = slot_counts[(df["Interview Capacity"] == 0) & (slot_counts > 0)]
    df.loc[~df["Active"], "Interview Capacity"] = 0
    df["Available Slots"] = df["Available Slots"].fillna("").astype(str)
    df["Background Tags"] = df["Background Tags"].fillna("").astype(str)
    df["Reviewer Notes"] = df["Reviewer Notes"].fillna("").astype(str)
    df["Availability Slot Count"] = df["Available Slots"].apply(lambda x: len(parse_slots(x))).astype(int)
    return df[["Reviewer Name", "Active", "Interview Capacity", "Available Slots", "Background Tags", "Reviewer Notes", "Availability Slot Count"]].reset_index(drop=True)


def normalize_candidate_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize either a simple candidate table or the RAUN candidate matrix."""
    raw = df.copy()
    matrix = _availability_matrix_to_rows(raw, "Full Name")
    if not matrix.empty:
        matrix["Applicant ID"] = pd.NA
        matrix["Email"] = ""
        matrix["Name Key"] = matrix["Full Name"].map(_person_match_key)
        return matrix[["Applicant ID", "Full Name", "Email", "Available Slots", "Availability Slot Count", "Under Reserve Slots", "Name Key"]].reset_index(drop=True)

    df = _promote_header_if_needed(df.copy())
    df.columns = [safe_text(c) for c in df.columns]
    rename = {
        "Name": "Full Name",
        "Applicant Name": "Full Name",
        "Candidate": "Full Name",
        "Candidate Name": "Full Name",
        "Availability": "Available Slots",
        "Available": "Available Slots",
        "Slots": "Available Slots",
        "Email address": "Email",
        "E-Mail": "Email",
    }
    df = df.rename(columns=rename)
    if "Applicant ID" not in df.columns:
        df["Applicant ID"] = pd.NA
    if "Full Name" not in df.columns:
        df["Full Name"] = ""
    if "Email" not in df.columns:
        df["Email"] = ""
    if "Available Slots" not in df.columns:
        id_cols = {"Applicant ID", "Full Name", "Email"}
        slot_cols = [c for c in df.columns if c not in id_cols]
        vals = []
        for _, row in df.iterrows():
            slots = []
            for c in slot_cols:
                if _is_yes_available(row.get(c, "")):
                    slots.append(str(c))
            vals.append(", ".join(slots))
        df["Available Slots"] = vals
    df["Applicant ID"] = pd.to_numeric(df["Applicant ID"], errors="coerce")
    df["Full Name"] = df["Full Name"].fillna("").astype(str).str.strip()
    df = df[df["Full Name"].ne("")].copy()
    df["Email"] = df["Email"].fillna("").astype(str).str.strip()
    df["Available Slots"] = df["Available Slots"].fillna("").astype(str)
    df["Availability Slot Count"] = df["Available Slots"].apply(lambda x: len(parse_slots(x))).astype(int)
    df["Under Reserve Slots"] = ""
    df["Name Key"] = df["Full Name"].map(_person_match_key)
    return df[["Applicant ID", "Full Name", "Email", "Available Slots", "Availability Slot Count", "Under Reserve Slots", "Name Key"]].reset_index(drop=True)


def _availability_lookup(df: pd.DataFrame, by: str) -> Dict[str, Set[str]]:
    if df is None or df.empty:
        return {}
    lookup = {}
    for _, row in df.iterrows():
        key = safe_text(row.get(by))
        if key:
            lookup[key] = parse_slots(row.get("Available Slots", ""))
    return lookup


def _availability_lookup_namekey(df: pd.DataFrame) -> Dict[str, Set[str]]:
    if df is None or df.empty:
        return {}
    out = {}
    for _, row in df.iterrows():
        key = safe_text(row.get("Name Key")) or _person_match_key(row.get("Full Name"))
        if key:
            out[key] = parse_slots(row.get("Available Slots", ""))
    return out


def _availability_lookup_email(df: pd.DataFrame) -> Dict[str, Set[str]]:
    if df is None or df.empty or "Email" not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        key = safe_text(row.get("Email")).lower()
        if key:
            out[key] = parse_slots(row.get("Available Slots", ""))
    return out


def _availability_lookup_id(df: pd.DataFrame) -> Dict[int, Set[str]]:
    if df is None or df.empty or "Applicant ID" not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        try:
            aid_raw = row.get("Applicant ID")
            if pd.isna(aid_raw):
                continue
            aid = int(aid_raw)
        except Exception:
            continue
        out[aid] = parse_slots(row.get("Available Slots", ""))
    return out


def _split_slot(slot: str) -> tuple[str, str]:
    text = safe_text(slot)
    if not text:
        return "", ""
    parts = text.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return text, ""



REVIEWER_ALIAS_KEYS = {
    "masha": "mariiakostetckaiamasha",
    "mariia kostetckaia masha": "mariiakostetckaiamasha",
    "billy": "billybatware",
    "ceci": "ceciliaveralagomarsino",
    "cecilia": "ceciliaveralagomarsino",
    "isabel saenz": "isabelsaenzhernandez",
    "isabel saenz hernandez": "isabelsaenzhernandez",
    "mary": "marypeloche",
    "nicola": "nicolajansen",
    "thi": "thihoang",
    "ghinwa": "ghinwamoujaes",
    "martina": "martinapardy",
    "samar": "samarmomin",
    "vanessa": "vanessamoser",
}

def _reviewer_match_key(value) -> str:
    base = _normalize_person_key(value)
    return REVIEWER_ALIAS_KEYS.get(base, base)

def allocate_interviews(
    interview_pool_df: pd.DataFrame,
    interviewers_df: pd.DataFrame,
    candidate_availability_df: pd.DataFrame | None = None,
    seed: int = 42,
    match_strength: str = "Low",
    prefer_preselection_reviewer: bool = True,
    require_availability_overlap: bool = False,
):
    """Allocate interviews with strict, slot-aware availability matching.

    This is intentionally simple and operational:
    - One candidate receives one interviewer and one slot.
    - One interviewer cannot receive two candidates in the same slot.
    - If candidate availability is uploaded and strict overlap is enabled, a
      candidate is only allocated when a shared candidate/interviewer slot exists.
    - Continuity is prioritised: one of the two preselection reviewers is chosen
      first whenever they have a valid shared slot and capacity.
    - If continuity is impossible, the app chooses another available interviewer
      and flags the exception.
    """
    rng = random.Random(seed)
    pool = interview_pool_df.copy() if interview_pool_df is not None else pd.DataFrame()

    # Build interviewer state.
    interviewers = {}
    for _, row in interviewers_df.iterrows():
        if not bool(row.get("Active", True)):
            continue
        name = safe_text(row.get("Reviewer Name"))
        if not name:
            continue
        try:
            cap = int(row.get("Interview Capacity", 0))
        except Exception:
            cap = 0
        slots = parse_slots(row.get("Available Slots", ""))
        # If slots are supplied and capacity is too high, the real hard limit is
        # the number of slots, because each slot can host only one interview for
        # that interviewer.
        if slots:
            cap = min(max(cap, 0), len(slots)) if cap > 0 else len(slots)
        if cap <= 0:
            continue
        interviewers[name] = {
            "capacity": cap,
            "assigned": 0,
            "tags": parse_tags(row.get("Background Tags", "")),
            "available_slots": slots,
            "used_slots": set(),
        }

    c_av_id = _availability_lookup_id(candidate_availability_df) if candidate_availability_df is not None else {}
    c_av_namekey = _availability_lookup_namekey(candidate_availability_df) if candidate_availability_df is not None else {}
    c_av_email = _availability_lookup_email(candidate_availability_df) if candidate_availability_df is not None else {}
    availability_uploaded = candidate_availability_df is not None and not candidate_availability_df.empty

    results = []
    exceptions = []

    # Candidates with fewer options should be allocated first. This greatly
    # improves final matching when availability is tight.
    working_rows = []
    for _, row in pool.iterrows():
        aid = int(row["Applicant ID"])
        full_name = safe_text(row.get("Full Name"))
        email = safe_text(row.get("Email"))
        candidate_slots = (
            c_av_id.get(aid, set())
            or c_av_email.get(email.lower(), set())
            or c_av_namekey.get(_person_match_key(full_name), set())
        )
        working_rows.append((len(candidate_slots) if candidate_slots else 10**6, rng.random(), row, candidate_slots))
    working_rows.sort(key=lambda x: (x[0], x[1]))

    for _slot_count, _noise, row, candidate_slots in working_rows:
        aid = int(row["Applicant ID"])
        full_name = safe_text(row.get("Full Name"))
        email = safe_text(row.get("Email"))
        tags = parse_tags(row.get("Background Tags", ""))
        pre1 = safe_text(row.get("Preselection Reviewer 1"))
        pre2 = safe_text(row.get("Preselection Reviewer 2"))
        pre_reviewers = {x for x in [pre1, pre2] if x}
        pre_reviewer_keys = {_reviewer_match_key(x) for x in pre_reviewers}

        candidate_options: List[Tuple[str, float, str, bool, bool]] = []
        for name, rv in interviewers.items():
            if rv["assigned"] >= rv["capacity"]:
                continue

            interviewer_slots = rv["available_slots"]
            available_for_this_interviewer = interviewer_slots - rv["used_slots"] if interviewer_slots else set()
            overlap_slots = set()
            if candidate_slots and available_for_this_interviewer:
                overlap_slots = candidate_slots.intersection(available_for_this_interviewer)
            elif not availability_uploaded and not interviewer_slots:
                # Manual coordination mode: no slot data at all.
                overlap_slots = set()

            # Strict mode should be honest: do not fabricate a match/date when
            # there is no shared slot. This is the mode needed for final matching.
            if require_availability_overlap and availability_uploaded:
                if not candidate_slots:
                    continue
                if not overlap_slots:
                    continue

            continuity = _reviewer_match_key(name) in pre_reviewer_keys
            topic_overlap = len(tags.intersection(rv["tags"]))
            load_ratio = rv["assigned"] / max(rv["capacity"], 1)
            score = rng.uniform(0, 0.1) - (load_ratio * 4.0) + _match_bonus(topic_overlap, match_strength)
            if overlap_slots:
                score += 1000.0
            if prefer_preselection_reviewer and continuity:
                score += 500.0
            chosen_slot = sorted(overlap_slots, key=_slot_sort_key)[0] if overlap_slots else ""
            candidate_options.append((name, score, chosen_slot, continuity, bool(overlap_slots)))

        candidate_options.sort(key=lambda x: x[1], reverse=True)
        interviewer = ""
        proposed_slot = ""
        continuity_used = False
        availability_overlap = False

        if candidate_options:
            interviewer, _score, proposed_slot, continuity_used, availability_overlap = candidate_options[0]
            interviewers[interviewer]["assigned"] += 1
            if proposed_slot:
                interviewers[interviewer]["used_slots"].add(proposed_slot)
        else:
            reason = "No active interviewer with remaining capacity met the current constraints."
            if availability_uploaded and require_availability_overlap and not candidate_slots:
                reason = "No matching candidate availability row was found by Applicant ID, email, or normalized name."
            elif availability_uploaded and require_availability_overlap:
                reason = "No interviewer had a shared available slot with this candidate."
            exceptions.append({
                "Applicant ID": aid,
                "Full Name": full_name,
                "Issue Type": "Unmatched candidate",
                "Details": reason,
            })

        if interviewer and prefer_preselection_reviewer and not continuity_used:
            exceptions.append({
                "Applicant ID": aid,
                "Full Name": full_name,
                "Issue Type": "Continuity not possible",
                "Details": "Neither preselection reviewer had a compatible available slot/capacity, so another interviewer was assigned.",
            })
        if interviewer and availability_uploaded and not candidate_slots:
            exceptions.append({
                "Applicant ID": aid,
                "Full Name": full_name,
                "Issue Type": "Candidate availability missing or unmatched",
                "Details": "No matching candidate availability row was found by Applicant ID, email, or normalized name.",
            })
        elif interviewer and availability_uploaded and not availability_overlap:
            exceptions.append({
                "Applicant ID": aid,
                "Full Name": full_name,
                "Issue Type": "No availability overlap found",
                "Details": "Interviewer was assigned without a shared slot. Use manual coordination or check availability data.",
            })

        interview_date, interview_time = _split_slot(proposed_slot)
        results.append({
            "Interviewer": interviewer,
            "Candidate": full_name,
            "Date": interview_date,
            "Time": interview_time,
            "Email address": email,
            "Interview email sent": "",
            "Interviewee confirmed": "",
            "Applicant ID": aid,
            "Program": row.get("Program", ""),
            "University": row.get("University", ""),
            "Field": row.get("Field", ""),
            "Preselection Reviewer 1": pre1,
            "Preselection Reviewer 2": pre2,
            "Reviewer 1 Invitation": row.get("Reviewer 1 Invitation", ""),
            "Reviewer 2 Invitation": row.get("Reviewer 2 Invitation", ""),
            "Final Result- First review": row.get("Final Result- First review", ""),
            "Total points from Reviewer 1": row.get("Total points from Reviewer 1", ""),
            "Total points from Reviewer 2": row.get("Total points from Reviewer 2", ""),
            "Total points from both reviewers": row.get("Total points from both reviewers", ""),
            "Continuity Used": "Yes" if continuity_used else "No",
            "Proposed Interview Slot": proposed_slot,
            "Availability Overlap Found": "Yes" if availability_overlap else "No",
            "Candidate Available Slots": ", ".join(sorted(candidate_slots, key=_slot_sort_key)),
        })

    result_df = pd.DataFrame(results) if results else pd.DataFrame()
    if not result_df.empty:
        result_df = result_df.sort_values(["Date", "Time", "Interviewer", "Candidate"], na_position="last").reset_index(drop=True)

    load_rows = []
    for name, rv in interviewers.items():
        assigned = rv["assigned"]
        cap = rv["capacity"]
        load_rows.append({
            "Reviewer Name": name,
            "Interview Assigned": assigned,
            "Interview Capacity": cap,
            "Remaining Interview Capacity": cap - assigned,
            "Interview Utilization %": round((assigned / cap * 100), 1) if cap > 0 else 0,
            "Availability Slot Count": len(rv["available_slots"]),
        })
    loads_df = pd.DataFrame(load_rows).sort_values(["Interview Assigned", "Reviewer Name"], ascending=[False, True]).reset_index(drop=True) if load_rows else pd.DataFrame()
    return result_df, loads_df, pd.DataFrame(exceptions)

# Compact alias override for robust continuity matching across short names used in availability sheets.
REVIEWER_ALIAS_KEYS_COMPACT = {
    "masha": "mariiakostetckaiamasha",
    "mariiakostetckaiamasha": "mariiakostetckaiamasha",
    "billy": "billybatware",
    "billybatware": "billybatware",
    "ceci": "ceciliaveralagomarsino",
    "cecilia": "ceciliaveralagomarsino",
    "ceciliaveralagomarsino": "ceciliaveralagomarsino",
    "isabelsaenz": "isabelsaenzhernandez",
    "isabelsaenzhernandez": "isabelsaenzhernandez",
    "mary": "marypeloche",
    "marypeloche": "marypeloche",
    "nicola": "nicolajansen",
    "nicolajansen": "nicolajansen",
    "thi": "thihoang",
    "thihoang": "thihoang",
    "ghinwa": "ghinwamoujaes",
    "ghinwamoujaes": "ghinwamoujaes",
    "martina": "martinapardy",
    "martinapardy": "martinapardy",
    "samar": "samarmomin",
    "samarmomin": "samarmomin",
    "vanessa": "vanessamoser",
    "vanessamoser": "vanessamoser",
}

def _reviewer_match_key(value) -> str:
    compact = _person_match_key(value)
    return REVIEWER_ALIAS_KEYS_COMPACT.get(compact, compact)

# =========================================================
# FINAL AVAILABILITY TEMPLATE / MATCHING OVERRIDES (v4)
# =========================================================
# These definitions intentionally override the earlier availability helpers.
# They support the clean templates generated by the app:
#   Interviewer sheet: row 1 = dates, row 2 = times, row 3+ = interviewer names + Yes/No cells
#   Candidate sheet: Applicant ID, Candidate, Email, then the same date/time slot grid.

AVAILABILITY_YES_VALUES = {"yes", "y", "true", "1", "x", "available", "ok"}
AVAILABILITY_RESERVE_VALUES = {"under reserve", "reserve", "maybe", "if needed", "ifneeded"}


def _slot_sort_key(slot: str):
    txt = safe_text(slot)
    if "|" in txt:
        d, t = [x.strip() for x in txt.split("|", 1)]
    else:
        parts = txt.split()
        d, t = (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")
    dt = pd.to_datetime(d, errors="coerce", dayfirst=True)
    if pd.isna(dt):
        return (pd.Timestamp.max, t)
    return (dt, t)


def _split_slot(slot: str):
    txt = safe_text(slot)
    if "|" in txt:
        d, t = [x.strip() for x in txt.split("|", 1)]
    else:
        parts = txt.split()
        d, t = (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")
    return d, t


def _person_match_key(value) -> str:
    text = safe_text(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8")
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _canonical_reviewer_display(value) -> str:
    raw = safe_text(value)
    key = _person_match_key(raw)
    alias_to_display = {
        "masha": "Mariia Kostetckaia (Masha)",
        "mariiakostetckaiamasha": "Mariia Kostetckaia (Masha)",
        "mariia": "Mariia Kostetckaia (Masha)",
        "billy": "Billy Batware",
        "billybatware": "Billy Batware",
        "ceci": "Cecilia Vera Lagomarsino",
        "cecilia": "Cecilia Vera Lagomarsino",
        "ceciliaveralagomarsino": "Cecilia Vera Lagomarsino",
        "isabel": "Isabel Sáenz Hernández",
        "isabelsaenz": "Isabel Sáenz Hernández",
        "isabelsaenzhernandez": "Isabel Sáenz Hernández",
        "mary": "Mary Peloche",
        "marypeloche": "Mary Peloche",
        "nicola": "Nicola Jansen",
        "nicolajansen": "Nicola Jansen",
        "thi": "Thi Hoang",
        "thihoang": "Thi Hoang",
        "martina": "Martina Pardy",
        "martinapardy": "Martina Pardy",
        "samar": "Samar Momin",
        "samarmomin": "Samar Momin",
        "vanessa": "Vanessa Moser",
        "vanessamoser": "Vanessa Moser",
        "laura": "Laura María García",
        "lauramariagarcia": "Laura María García",
        "florian": "Florian Müller",
        "florianmuller": "Florian Müller",
        "roman": "Roman Hoffmann",
        "romanhoffmann": "Roman Hoffmann",
        "ivy": "Ivy Omondi",
        "ivyomondi": "Ivy Omondi",
        "berkay": "Berkay Öztürk",
        "berkayoztturk": "Berkay Öztürk",
        "berkayozdurtk": "Berkay Öztürk",
        "berkayozturk": "Berkay Öztürk",
    }
    return alias_to_display.get(key, raw)


REVIEWER_ALIAS_KEYS_COMPACT = {
    "masha": "mariiakostetckaiamasha",
    "mariiakostetckaiamasha": "mariiakostetckaiamasha",
    "mariia": "mariiakostetckaiamasha",
    "billy": "billybatware",
    "billybatware": "billybatware",
    "ceci": "ceciliaveralagomarsino",
    "cecilia": "ceciliaveralagomarsino",
    "ceciliaveralagomarsino": "ceciliaveralagomarsino",
    "isabel": "isabelsaenzhernandez",
    "isabelsaenz": "isabelsaenzhernandez",
    "isabelsaenzhernandez": "isabelsaenzhernandez",
    "mary": "marypeloche",
    "marypeloche": "marypeloche",
    "nicola": "nicolajansen",
    "nicolajansen": "nicolajansen",
    "thi": "thihoang",
    "thihoang": "thihoang",
    "martina": "martinapardy",
    "martinapardy": "martinapardy",
    "samar": "samarmomin",
    "samarmomin": "samarmomin",
    "vanessa": "vanessamoser",
    "vanessamoser": "vanessamoser",
    "laura": "lauramariagarcia",
    "lauramariagarcia": "lauramariagarcia",
    "florian": "florianmuller",
    "florianmuller": "florianmuller",
    "roman": "romanhoffmann",
    "romanhoffmann": "romanhoffmann",
    "ivy": "ivyomondi",
    "ivyomondi": "ivyomondi",
    "berkay": "berkayozturk",
    "berkayozturk": "berkayozturk",
}


def _reviewer_match_key(value) -> str:
    compact = _person_match_key(value)
    return REVIEWER_ALIAS_KEYS_COMPACT.get(compact, compact)


def _is_yes_cell(value) -> bool:
    s = safe_text(value).lower()
    return s in AVAILABILITY_YES_VALUES


def _is_reserve_cell(value) -> bool:
    s = safe_text(value).lower()
    return s in AVAILABILITY_RESERVE_VALUES


def _format_date_cell(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%d-%m-%Y")
    dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.notna(dt):
        return dt.strftime("%d-%m-%Y")
    return safe_text(value)


def _format_time_cell(value) -> str:
    if pd.isna(value):
        return ""
    # Excel times sometimes arrive as a fraction of a day.
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if 0 <= float(value) < 1:
            total_minutes = int(round(float(value) * 24 * 60))
            return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
    dt = pd.to_datetime(value, errors="coerce")
    if pd.notna(dt) and safe_text(value).lower() not in {"nan", "nat"}:
        # Only use time if the input looked like a time/date-time, not a date-only header.
        raw = safe_text(value)
        if ":" in raw or "am" in raw.lower() or "pm" in raw.lower():
            return dt.strftime("%H:%M")
    raw = safe_text(value)
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?$", raw)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"
    return raw


def _detect_slot_start(raw: pd.DataFrame) -> int:
    """Find first column that has a date-like value in row 0 and time-like value in row 1."""
    if raw is None or raw.empty or len(raw) < 2:
        return 1
    for j in range(raw.shape[1]):
        d = _format_date_cell(raw.iat[0, j])
        t = _format_time_cell(raw.iat[1, j])
        if d and t:
            # avoid treating identity columns as slots
            if d.lower() not in {"name", "candidate", "email", "applicant id", "reviewer name", "interviewer"}:
                return j
    return 1


def _matrix_to_availability_rows(raw_df: pd.DataFrame, person_col_name: str) -> pd.DataFrame:
    raw = raw_df.copy() if raw_df is not None else pd.DataFrame()
    if raw.empty or raw.shape[0] < 3 or raw.shape[1] < 2:
        return pd.DataFrame()
    raw = raw.dropna(axis=1, how="all")
    if raw.empty or raw.shape[0] < 3:
        return pd.DataFrame()
    slot_start = _detect_slot_start(raw)
    slot_cols = []
    for j in range(slot_start, raw.shape[1]):
        d = _format_date_cell(raw.iat[0, j])
        t = _format_time_cell(raw.iat[1, j])
        if d and t:
            slot_cols.append((j, f"{d} | {t}"))
    if not slot_cols:
        return pd.DataFrame()

    rows = []
    for i in range(2, raw.shape[0]):
        # Candidate template first columns = Applicant ID, Candidate, Email.
        # Interviewer template first column = Interviewer.
        if person_col_name == "Full Name":
            applicant_id = raw.iat[i, 0] if raw.shape[1] > 0 else ""
            person = raw.iat[i, 1] if raw.shape[1] > 1 else ""
            email = raw.iat[i, 2] if raw.shape[1] > 2 else ""
        else:
            applicant_id = ""
            person = raw.iat[i, 0] if raw.shape[1] > 0 else ""
            email = ""
        person = safe_text(person)
        if not person:
            continue
        yes_slots = []
        reserve_slots = []
        for j, slot in slot_cols:
            val = raw.iat[i, j] if j < raw.shape[1] else ""
            if _is_yes_cell(val):
                yes_slots.append(slot)
            elif _is_reserve_cell(val):
                reserve_slots.append(slot)
        rows.append({
            "Applicant ID": applicant_id,
            person_col_name: person,
            "Email": safe_text(email),
            "Available Slots": ", ".join(sorted(yes_slots, key=_slot_sort_key)),
            "Availability Slot Count": len(yes_slots),
            "Under Reserve Slots": ", ".join(sorted(reserve_slots, key=_slot_sort_key)),
        })
    return pd.DataFrame(rows)


def normalize_interviewers_input(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize interviewer availability from the app-generated matrix or a simple table."""
    raw = df.copy() if df is not None else pd.DataFrame()
    matrix = _matrix_to_availability_rows(raw, "Reviewer Name")
    if not matrix.empty:
        matrix["Reviewer Name"] = matrix["Reviewer Name"].map(_canonical_reviewer_display)
        matrix["Active"] = matrix["Availability Slot Count"].astype(int) > 0
        matrix["Interview Capacity"] = matrix["Availability Slot Count"].astype(int)
        matrix["Background Tags"] = ""
        matrix["Reviewer Notes"] = matrix.apply(
            lambda r: f"Loaded from availability template. Under reserve slots: {r.get('Under Reserve Slots','')}" if safe_text(r.get("Under Reserve Slots")) else "Loaded from availability template.",
            axis=1,
        )
        return matrix[["Reviewer Name", "Active", "Interview Capacity", "Available Slots", "Background Tags", "Reviewer Notes", "Availability Slot Count", "Under Reserve Slots"]].reset_index(drop=True)

    out = raw.copy()
    out.columns = [safe_text(c) for c in out.columns]
    out = out.rename(columns={
        "Reviewer": "Reviewer Name",
        "Name": "Reviewer Name",
        "Interviewer": "Reviewer Name",
        "Interviewer name": "Reviewer Name",
        "Capacity": "Interview Capacity",
        "Can Interview": "Active",
        "Availability": "Available Slots",
        "Available": "Available Slots",
        "Slots": "Available Slots",
    })
    for col, default in {
        "Reviewer Name": "", "Active": True, "Interview Capacity": 0,
        "Available Slots": "", "Background Tags": "", "Reviewer Notes": "",
    }.items():
        if col not in out.columns:
            out[col] = default
    out["Reviewer Name"] = out["Reviewer Name"].fillna("").astype(str).str.strip().map(_canonical_reviewer_display)
    out = out[out["Reviewer Name"].ne("")].copy()
    out["Active"] = out["Active"].apply(lambda x: _bool_from_text(x, True))
    out["Interview Capacity"] = pd.to_numeric(out["Interview Capacity"], errors="coerce").fillna(0).astype(int).clip(lower=0)
    out.loc[~out["Active"], "Interview Capacity"] = 0
    out["Available Slots"] = out["Available Slots"].fillna("").astype(str)
    out["Availability Slot Count"] = out["Available Slots"].map(lambda x: len(parse_slots(x)))
    # When slots are supplied, capacity cannot exceed number of actual available slots.
    has_slots = out["Availability Slot Count"] > 0
    out.loc[has_slots, "Interview Capacity"] = out.loc[has_slots, ["Interview Capacity", "Availability Slot Count"]].min(axis=1)
    out["Background Tags"] = out["Background Tags"].fillna("").astype(str)
    out["Reviewer Notes"] = out["Reviewer Notes"].fillna("").astype(str)
    if "Under Reserve Slots" not in out.columns:
        out["Under Reserve Slots"] = ""
    return out[["Reviewer Name", "Active", "Interview Capacity", "Available Slots", "Background Tags", "Reviewer Notes", "Availability Slot Count", "Under Reserve Slots"]].reset_index(drop=True)


def normalize_candidate_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize candidate availability from the app-generated matrix or a simple table."""
    raw = df.copy() if df is not None else pd.DataFrame()
    matrix = _matrix_to_availability_rows(raw, "Full Name")
    if not matrix.empty:
        matrix["Applicant ID"] = pd.to_numeric(matrix["Applicant ID"], errors="coerce")
        matrix["Full Name"] = matrix["Full Name"].fillna("").astype(str).str.strip()
        matrix["Email"] = matrix["Email"].fillna("").astype(str).str.strip()
        matrix["Name Key"] = matrix["Full Name"].map(_person_match_key)
        return matrix[["Applicant ID", "Full Name", "Email", "Available Slots", "Availability Slot Count", "Under Reserve Slots", "Name Key"]].reset_index(drop=True)

    out = raw.copy()
    out.columns = [safe_text(c) for c in out.columns]
    out = out.rename(columns={"Name": "Full Name", "Applicant Name": "Full Name", "Candidate": "Full Name", "Availability": "Available Slots", "Slots": "Available Slots", "Email address": "Email"})
    if "Applicant ID" not in out.columns:
        out["Applicant ID"] = pd.NA
    if "Full Name" not in out.columns:
        out["Full Name"] = ""
    if "Email" not in out.columns:
        out["Email"] = ""
    if "Available Slots" not in out.columns:
        id_cols = {"Applicant ID", "Full Name", "Candidate", "Email", "Email address"}
        slot_cols = [c for c in out.columns if c not in id_cols]
        out["Available Slots"] = [
            ", ".join(str(c) for c in slot_cols if _is_yes_cell(row.get(c, "")))
            for _, row in out.iterrows()
        ]
    out["Applicant ID"] = pd.to_numeric(out["Applicant ID"], errors="coerce")
    out["Full Name"] = out["Full Name"].fillna("").astype(str).str.strip()
    out["Email"] = out["Email"].fillna("").astype(str).str.strip()
    out["Available Slots"] = out["Available Slots"].fillna("").astype(str)
    out["Availability Slot Count"] = out["Available Slots"].map(lambda x: len(parse_slots(x)))
    out["Under Reserve Slots"] = out["Under Reserve Slots"].fillna("").astype(str) if "Under Reserve Slots" in out.columns else ""
    out["Name Key"] = out["Full Name"].map(_person_match_key)
    return out[["Applicant ID", "Full Name", "Email", "Available Slots", "Availability Slot Count", "Under Reserve Slots", "Name Key"]].reset_index(drop=True)


def _availability_lookup_namekey(df: pd.DataFrame) -> Dict[str, Set[str]]:
    if df is None or df.empty:
        return {}
    out = {}
    for _, row in df.iterrows():
        key = safe_text(row.get("Name Key")) or _person_match_key(row.get("Full Name"))
        if key:
            out[key] = parse_slots(row.get("Available Slots", ""))
    return out


def _availability_lookup_email(df: pd.DataFrame) -> Dict[str, Set[str]]:
    if df is None or df.empty or "Email" not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        key = safe_text(row.get("Email")).lower()
        if key:
            out[key] = parse_slots(row.get("Available Slots", ""))
    return out


def _availability_lookup_id(df: pd.DataFrame) -> Dict[int, Set[str]]:
    if df is None or df.empty or "Applicant ID" not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        if pd.isna(row.get("Applicant ID")):
            continue
        try:
            key = int(row.get("Applicant ID"))
        except Exception:
            continue
        out[key] = parse_slots(row.get("Available Slots", ""))
    return out


def allocate_interviews(
    interview_pool_df: pd.DataFrame,
    interviewers_df: pd.DataFrame,
    candidate_availability_df: pd.DataFrame | None = None,
    seed: int = 42,
    match_strength: str = "Low",
    prefer_preselection_reviewer: bool = True,
    require_availability_overlap: bool = True,
):
    """Slot-aware interview matching.

    Matching priority:
    1. One of the two original preselection reviewers, if that reviewer has a shared available slot.
    2. Any other active interviewer with a shared available slot.
    3. If strict overlap is off, allocate by continuity/capacity without a slot and flag for manual coordination.

    The same interviewer cannot be assigned to two candidates at the same date/time.
    """
    rng = random.Random(seed)
    pool = interview_pool_df.copy() if interview_pool_df is not None else pd.DataFrame()
    interviewers = {}
    for _, row in interviewers_df.iterrows():
        if not bool(row.get("Active", True)):
            continue
        name = safe_text(row.get("Reviewer Name"))
        if not name:
            continue
        try:
            cap = int(row.get("Interview Capacity", 0))
        except Exception:
            cap = 0
        slots = parse_slots(row.get("Available Slots", ""))
        if slots:
            cap = min(max(cap, 0), len(slots)) if cap > 0 else len(slots)
        if cap <= 0:
            continue
        interviewers[name] = {
            "capacity": cap,
            "assigned": 0,
            "tags": parse_tags(row.get("Background Tags", "")),
            "available_slots": slots,
            "used_slots": set(),
        }

    c_av_id = _availability_lookup_id(candidate_availability_df)
    c_av_email = _availability_lookup_email(candidate_availability_df)
    c_av_namekey = _availability_lookup_namekey(candidate_availability_df)
    availability_uploaded = candidate_availability_df is not None and not candidate_availability_df.empty

    rows_with_options = []
    for _, row in pool.iterrows():
        aid = int(row.get("Applicant ID"))
        full_name = safe_text(row.get("Full Name"))
        email = safe_text(row.get("Email"))
        slots = c_av_id.get(aid, set()) or c_av_email.get(email.lower(), set()) or c_av_namekey.get(_person_match_key(full_name), set())
        rows_with_options.append((len(slots) if slots else 10**6, rng.random(), row, slots))
    rows_with_options.sort(key=lambda x: (x[0], x[1]))

    results = []
    exceptions = []

    for _, _, row, candidate_slots in rows_with_options:
        aid = int(row.get("Applicant ID"))
        full_name = safe_text(row.get("Full Name"))
        email = safe_text(row.get("Email"))
        tags = parse_tags(row.get("Background Tags", ""))
        pre1 = safe_text(row.get("Preselection Reviewer 1"))
        pre2 = safe_text(row.get("Preselection Reviewer 2"))
        pre_keys = {_reviewer_match_key(x) for x in [pre1, pre2] if safe_text(x)}

        options = []
        for name, rv in interviewers.items():
            if rv["assigned"] >= rv["capacity"]:
                continue
            free_slots = rv["available_slots"] - rv["used_slots"] if rv["available_slots"] else set()
            overlap_slots = candidate_slots.intersection(free_slots) if candidate_slots and free_slots else set()
            if availability_uploaded and require_availability_overlap:
                if not candidate_slots or not overlap_slots:
                    continue
            continuity = _reviewer_match_key(name) in pre_keys
            topic_overlap = len(tags.intersection(rv["tags"]))
            load_ratio = rv["assigned"] / max(rv["capacity"], 1)
            score = rng.uniform(0, 0.1) - (load_ratio * 4.0) + _match_bonus(topic_overlap, match_strength)
            if continuity and prefer_preselection_reviewer:
                score += 10000.0
            if overlap_slots:
                score += 1000.0
            chosen_slot = sorted(overlap_slots, key=_slot_sort_key)[0] if overlap_slots else ""
            options.append((name, score, chosen_slot, continuity, bool(overlap_slots)))

        options.sort(key=lambda x: x[1], reverse=True)
        interviewer = ""
        proposed_slot = ""
        continuity_used = False
        overlap_found = False
        if options:
            interviewer, _, proposed_slot, continuity_used, overlap_found = options[0]
            interviewers[interviewer]["assigned"] += 1
            if proposed_slot:
                interviewers[interviewer]["used_slots"].add(proposed_slot)
        else:
            if availability_uploaded and not candidate_slots:
                reason = "Candidate availability missing or could not be matched by Applicant ID, email, or name."
            elif availability_uploaded and require_availability_overlap:
                reason = "No interviewer has a shared available slot with this candidate."
            else:
                reason = "No active interviewer with remaining capacity."
            exceptions.append({"Applicant ID": aid, "Full Name": full_name, "Issue Type": "Unmatched candidate", "Details": reason})

        if interviewer and prefer_preselection_reviewer and not continuity_used:
            exceptions.append({"Applicant ID": aid, "Full Name": full_name, "Issue Type": "Continuity not possible", "Details": "Neither original reviewer had a compatible available slot/capacity; another interviewer was assigned."})
        if interviewer and availability_uploaded and not overlap_found:
            exceptions.append({"Applicant ID": aid, "Full Name": full_name, "Issue Type": "No date/time match", "Details": "Assigned without a shared date/time slot because strict overlap was off."})

        d, t = _split_slot(proposed_slot)
        results.append({
            "Interviewer": interviewer,
            "Candidate": full_name,
            "Date": d,
            "Time": t,
            "Email address": email,
            "Interview email sent": "",
            "Interviewee confirmed": "",
            "Applicant ID": aid,
            "Program": row.get("Program", ""),
            "University": row.get("University", ""),
            "Field": row.get("Field", ""),
            "Preselection Reviewer 1": pre1,
            "Preselection Reviewer 2": pre2,
            "Reviewer 1 Invitation": row.get("Reviewer 1 Invitation", ""),
            "Reviewer 2 Invitation": row.get("Reviewer 2 Invitation", ""),
            "Final Result- First review": row.get("Final Result- First review", ""),
            "Continuity Used": "Yes" if continuity_used else "No",
            "Availability Overlap Found": "Yes" if overlap_found else "No",
            "Candidate Available Slots": ", ".join(sorted(candidate_slots, key=_slot_sort_key)),
            "Proposed Interview Slot": proposed_slot,
        })

    result_df = pd.DataFrame(results) if results else pd.DataFrame()
    if not result_df.empty:
        result_df = result_df.sort_values(["Date", "Time", "Interviewer", "Candidate"], na_position="last").reset_index(drop=True)
    load_rows = []
    for name, rv in interviewers.items():
        assigned = rv["assigned"]
        cap = rv["capacity"]
        load_rows.append({
            "Reviewer Name": name,
            "Interview Assigned": assigned,
            "Interview Capacity": cap,
            "Remaining Interview Capacity": cap - assigned,
            "Interview Utilization %": round((assigned / cap * 100), 1) if cap > 0 else 0,
            "Availability Slot Count": len(rv["available_slots"]),
        })
    loads_df = pd.DataFrame(load_rows).sort_values(["Interview Assigned", "Reviewer Name"], ascending=[False, True]).reset_index(drop=True) if load_rows else pd.DataFrame()
    return result_df, loads_df, pd.DataFrame(exceptions)
