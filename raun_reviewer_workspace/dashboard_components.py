from __future__ import annotations
import pandas as pd
import plotly.express as px
import streamlit as st

from .assessment_logic import is_completed, normalize_decision
from .data_io import make_streamlit_safe_df


def reviewer_role_for_candidate(row: pd.Series, reviewer: str) -> list[str]:
    roles = []
    if str(row.get("Reviewer 1", "")).strip() == reviewer:
        roles.append("Reviewer 1")
    if str(row.get("Reviewer 2", "")).strip() == reviewer:
        roles.append("Reviewer 2")
    if str(row.get("Interviewer", "")).strip() == reviewer:
        roles.append("Interviewer")
    return roles


def assigned_filter(df: pd.DataFrame, reviewer: str, mode: str, admin_view_all: bool = False) -> pd.DataFrame:
    """Return the visible candidates for a reviewer/interviewer.

    Admin users still see their own workload by default. They only see all
    candidates after explicitly selecting the all-reviewers/interviewers option.
    """
    if admin_view_all or not reviewer:
        return df.copy()
    if mode == "preselection":
        mask = (df["Reviewer 1"].astype(str).str.strip() == reviewer) | (df["Reviewer 2"].astype(str).str.strip() == reviewer)
    else:
        mask = df.get("Interviewer", pd.Series([""] * len(df))).astype(str).str.strip() == reviewer
        if not mask.any():
            mask = df.get("Interview Required", pd.Series([""] * len(df))).astype(str).str.strip().ne("No")
    return df.loc[mask].copy()


def progress_table(df: pd.DataFrame) -> pd.DataFrame:
    reviewers = sorted(set(df["Reviewer 1"].dropna().astype(str).str.strip()) | set(df["Reviewer 2"].dropna().astype(str).str.strip()))
    reviewers = [r for r in reviewers if r and r.lower() != "nan"]
    rows = []
    for reviewer in reviewers:
        r1_mask = df["Reviewer 1"].astype(str).str.strip() == reviewer
        r2_mask = df["Reviewer 2"].astype(str).str.strip() == reviewer
        assigned = int(r1_mask.sum() + r2_mask.sum())
        r1_completed = df.loc[r1_mask].apply(lambda r: is_completed(r.get("R1 Invitation"), r.get("R1 Total")), axis=1).sum() if r1_mask.any() else 0
        r2_completed = df.loc[r2_mask].apply(lambda r: is_completed(r.get("R2 Invitation"), r.get("R2 Total")), axis=1).sum() if r2_mask.any() else 0
        decisions = []
        scores = []
        top5 = 0
        for _, r in df.loc[r1_mask].iterrows():
            decisions.append(normalize_decision(r.get("R1 Invitation")) or "Pending")
            try: scores.append(float(r.get("R1 Total") or 0))
            except Exception: pass
            if str(r.get("R1 Top5", "")).casefold().startswith("yes"): top5 += 1
        for _, r in df.loc[r2_mask].iterrows():
            decisions.append(normalize_decision(r.get("R2 Invitation")) or "Pending")
            try: scores.append(float(r.get("R2 Total") or 0))
            except Exception: pass
            if str(r.get("R2 Top5", "")).casefold().startswith("yes"): top5 += 1
        scored = [s for s in scores if s > 0]
        rows.append({
            "Reviewer Name": reviewer,
            "Assigned as Reviewer 1": int(r1_mask.sum()),
            "Assigned as Reviewer 2": int(r2_mask.sum()),
            "Total Assigned": assigned,
            "Completed": int(r1_completed + r2_completed),
            "Pending": int(assigned - r1_completed - r2_completed),
            "Yes": decisions.count("Yes"),
            "Maybe": decisions.count("Maybe"),
            "No": decisions.count("No"),
            "Pending Decision": decisions.count("Pending"),
            "Top-5": top5,
            "Average Score": round(sum(scored) / max(1, len(scored)), 2),
        })
    return make_streamlit_safe_df(pd.DataFrame(rows))


def _clean_series(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip().replace({"": "Not specified", "nan": "Not specified", "NaN": "Not specified", "None": "Not specified"})


def _value_counts(df: pd.DataFrame, col: str, top_n: int | None = None) -> pd.DataFrame:
    if col not in df.columns or df.empty:
        return pd.DataFrame(columns=[col, "Count"])
    vc = _clean_series(df[col]).value_counts(dropna=False).reset_index()
    vc.columns = [col, "Count"]
    if top_n and len(vc) > top_n:
        top = vc.head(top_n).copy()
        other_count = int(vc["Count"].iloc[top_n:].sum())
        top.loc[len(top)] = ["Other", other_count]
        return top
    return vc


def _numeric_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce").dropna()


def _pie(df: pd.DataFrame, col: str, title: str, key: str, top_n: int | None = 10):
    data = _value_counts(df, col, top_n=top_n)
    if data.empty:
        st.info(f"No data available for {title}.")
        return
    fig = px.pie(data, names=col, values="Count", title=title, hole=0.35)
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=60, b=10))
    st.plotly_chart(fig, use_container_width=True, key=key)


def _bar(df: pd.DataFrame, col: str, title: str, key: str, top_n: int = 15, horizontal: bool = False):
    data = _value_counts(df, col, top_n=top_n)
    if data.empty:
        st.info(f"No data available for {title}.")
        return
    if horizontal:
        data = data.sort_values("Count", ascending=True)
        fig = px.bar(data, x="Count", y=col, orientation="h", title=title)
    else:
        fig = px.bar(data, x=col, y="Count", title=title)
    fig.update_layout(height=400, margin=dict(l=10, r=10, t=60, b=40))
    st.plotly_chart(fig, use_container_width=True, key=key)


def _render_applicant_overview(df: pd.DataFrame, view: pd.DataFrame, mode: str):
    st.markdown("### Applicant overview dashboard")
    st.caption("Charts below use the currently visible candidates by default. Expand the global dashboard to compare against the full loaded sheet.")

    with st.expander("Global dashboard for all loaded applicants", expanded=True):
        global_df = df.copy()
        c1, c2, c3 = st.columns(3)
        with c1:
            _pie(global_df, "Program", "Programme distribution", f"{mode}_global_program_pie")
        with c2:
            _pie(global_df, "Gender", "Gender distribution", f"{mode}_global_gender_pie")
        with c3:
            _pie(global_df, "Applied for Scholarship", "Scholarship applications", f"{mode}_global_scholarship_pie")
        c4, c5 = st.columns(2)
        with c4:
            _bar(global_df, "Country of Residence", "Top countries of residence", f"{mode}_global_residence_bar", top_n=12, horizontal=True)
        with c5:
            _bar(global_df, "Country of Citizenship", "Top countries of citizenship", f"{mode}_global_citizenship_bar", top_n=12, horizontal=True)
        c6, c7 = st.columns(2)
        with c6:
            _bar(global_df, "University", "Top universities", f"{mode}_global_university_bar", top_n=15, horizontal=True)
        with c7:
            age = _numeric_series(global_df, "Age")
            if not age.empty:
                fig = px.histogram(pd.DataFrame({"Age": age}), x="Age", nbins=18, title="Applicant age distribution")
                fig.update_layout(height=400, margin=dict(l=10, r=10, t=60, b=40))
                st.plotly_chart(fig, use_container_width=True, key=f"{mode}_global_age_hist")
            else:
                st.info("No numeric age data available.")
        c8, c9, c10 = st.columns(3)
        with c8:
            _bar(global_df, "Area 1", "Research Area 1", f"{mode}_global_area1_bar", top_n=12, horizontal=True)
        with c9:
            _bar(global_df, "Area 2", "Research Area 2", f"{mode}_global_area2_bar", top_n=12, horizontal=True)
        with c10:
            _bar(global_df, "Area 3", "Research Area 3", f"{mode}_global_area3_bar", top_n=12, horizontal=True)
        if "Country of Residence" in global_df.columns:
            country_counts = _value_counts(global_df, "Country of Residence", top_n=None)
            country_counts = country_counts[country_counts["Country of Residence"] != "Not specified"]
            if not country_counts.empty:
                fig = px.choropleth(country_counts, locations="Country of Residence", locationmode="country names", color="Count", hover_name="Country of Residence", title="Country of residence map")
                fig.update_layout(height=440, margin=dict(l=10, r=10, t=60, b=10))
                st.plotly_chart(fig, use_container_width=True, key=f"{mode}_global_country_map")

    st.markdown("### Your current working list")
    c1, c2, c3 = st.columns(3)
    with c1:
        _pie(view, "Program", "Your list - programme", f"{mode}_view_program_pie")
    with c2:
        _pie(view, "Country of Residence", "Your list - residence", f"{mode}_view_residence_pie", top_n=8)
    with c3:
        _pie(view, "Applied for Scholarship", "Your list - scholarship", f"{mode}_view_scholarship_pie")


def render_dashboard(df: pd.DataFrame, reviewer: str, mode: str, admin_view: bool = False) -> None:
    view = assigned_filter(df, reviewer, mode, admin_view)
    total = len(df)
    assigned = len(view)
    if mode == "preselection":
        completed = 0
        for _, row in view.iterrows():
            if str(row.get("Reviewer 1", "")).strip() == reviewer or admin_view:
                completed += int(is_completed(row.get("R1 Invitation"), row.get("R1 Total")))
            if str(row.get("Reviewer 2", "")).strip() == reviewer or admin_view:
                completed += int(is_completed(row.get("R2 Invitation"), row.get("R2 Total")))
        expected = assigned if not admin_view else assigned * 2
    else:
        completed = view["Interview Total"].map(lambda x: str(x).strip() not in {"", "0", "0.0", "nan", "Not scored"}).sum() if "Interview Total" in view else 0
        expected = assigned
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total applicants loaded", total)
    c2.metric("Applicants in this view", assigned)
    c3.metric("Completed assessments", int(completed))
    c4.metric("Pending assessments", max(0, int(expected - completed)))

    _render_applicant_overview(df, view, mode)

    if mode == "preselection":
        st.markdown("### Reviewer progress and assessment status")
        prog = progress_table(df)
        st.dataframe(prog, use_container_width=True, hide_index=True)
        col1, col2 = st.columns(2)
        with col1:
            decisions = []
            for _, r in view.iterrows():
                if admin_view or str(r.get("Reviewer 1", "")).strip() == reviewer:
                    decisions.append(normalize_decision(r.get("R1 Invitation")) or "Pending")
                if admin_view or str(r.get("Reviewer 2", "")).strip() == reviewer:
                    decisions.append(normalize_decision(r.get("R2 Invitation")) or "Pending")
            dec_df = pd.DataFrame({"Decision": decisions}).value_counts().reset_index(name="Count") if decisions else pd.DataFrame(columns=["Decision", "Count"])
            if not dec_df.empty:
                fig = px.pie(dec_df, names="Decision", values="Count", title="Decision distribution", hole=0.35)
                fig.update_layout(height=360, margin=dict(l=10, r=10, t=60, b=10))
                st.plotly_chart(fig, use_container_width=True, key=f"{mode}_decision_pie")
        with col2:
            scores = []
            for _, r in view.iterrows():
                for col in ["R1 Total", "R2 Total"]:
                    try:
                        v = float(r.get(col) or 0)
                        if v > 0: scores.append(v)
                    except Exception:
                        pass
            if scores:
                fig = px.histogram(pd.DataFrame({"Score": scores}), x="Score", nbins=16, title="Score distribution")
                fig.update_layout(height=360, margin=dict(l=10, r=10, t=60, b=40))
                st.plotly_chart(fig, use_container_width=True, key=f"{mode}_score_hist")
    else:
        st.markdown("### Interview assessment status")
        col1, col2 = st.columns(2)
        with col1:
            if "Interview Recommended" in view.columns:
                dec = _clean_series(view["Interview Recommended"]).value_counts().reset_index()
                dec.columns = ["Recommendation", "Count"]
                if not dec.empty:
                    fig = px.pie(dec, names="Recommendation", values="Count", title="Interview recommendation distribution", hole=0.35)
                    fig.update_layout(height=360, margin=dict(l=10, r=10, t=60, b=10))
                    st.plotly_chart(fig, use_container_width=True, key=f"{mode}_reco_pie")
        with col2:
            scores = _numeric_series(view, "Interview Total")
            scores = scores[scores > 0]
            if not scores.empty:
                fig = px.histogram(pd.DataFrame({"Interview Total": scores}), x="Interview Total", nbins=12, title="Interview score distribution")
                fig.update_layout(height=360, margin=dict(l=10, r=10, t=60, b=40))
                st.plotly_chart(fig, use_container_width=True, key=f"{mode}_score_hist")
