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
    df["Reviewer Name"] = df["Reviewer Name"].fillna("").astype(str).str.strip()
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
            continuity = name in pre_reviewers
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
