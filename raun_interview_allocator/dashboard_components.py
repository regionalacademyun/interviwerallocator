import re
from typing import Iterable, List

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import streamlit as st
from wordcloud import STOPWORDS, WordCloud

from .interview_logic import compute_planning_metrics
from .data_io import make_streamlit_safe_df

UNIVERSITY_STOPWORDS = {
    "university", "universitat", "universidad", "universite", "universität",
    "school", "institute", "institut", "college", "faculty", "centre", "center",
    "academy", "of", "the", "for", "and", "in", "at", "de", "di", "la", "le",
    "del", "della", "state", "main", "current", "enrolment",
}
FIELD_STOPWORDS = {
    "studies", "study", "program", "programme", "master", "masters", "bachelor",
    "bachelors", "phd", "degree", "specialization", "specialisation", "semester",
    "second", "first", "equivalent", "field", "current", "level", "of", "the",
    "and", "for", "in", "to", "based", "area",
}
PLOTLY_PALETTE = [
    "#2563EB", "#0EA5E9", "#10B981", "#8B5CF6",
    "#F59E0B", "#EF4444", "#14B8A6", "#F97316",
]
YES_VALUES = {"yes", "y", "true", "1"}
NO_VALUES = {"no", "n", "false", "0"}


def app_styles():
    st.markdown(
        '''
        <style>
        .main .block-container {padding-top: 1rem; padding-bottom: 1.8rem; max-width: 1500px;}
        .hero {
            border-radius:22px; padding:1.2rem 1.3rem;
            background:linear-gradient(135deg,#eef6ff,#ffffff,#eefdf6);
            border:1px solid rgba(148,163,184,0.25);
            box-shadow: 0 12px 28px rgba(15,23,42,0.08);
            margin-bottom:1rem;
        }
        .step {
            border-radius:18px; padding:1rem 1.05rem;
            background:linear-gradient(135deg,#ffffff,#f8fbff);
            border:1px solid rgba(148,163,184,0.18);
            box-shadow:0 8px 18px rgba(15,23,42,0.04);
            margin-bottom:1rem;
        }
        .explain {font-size:0.96rem; color:#475569;}
        .mini-sub {font-size:0.88rem; color:#64748b; margin-top:-0.25rem;}
        .soft-note {background:#f8fafc; border:1px solid #e2e8f0; padding:0.75rem 0.9rem; border-radius:14px; color:#475569;}
        </style>
        ''',
        unsafe_allow_html=True,
    )


def _clean_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype="object")
    s = df[column].fillna("").astype(str).str.strip()
    return s[s != ""]


def _tokenize_text(values: Iterable[str], stopwords: set[str]) -> str:
    tokens: List[str] = []
    for val in values:
        pieces = re.findall(r"[A-Za-zÀ-ÿ0-9\-']+", str(val))
        for token in pieces:
            lowered = token.lower()
            if lowered in stopwords or len(lowered) <= 1:
                continue
            tokens.append(token)
    return " ".join(tokens)


def _metric_subtext(text: str):
    st.markdown(f"<div class='mini-sub'>{text}</div>", unsafe_allow_html=True)


def _normalize_yes_no(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip().str.lower()
    out = pd.Series("No response", index=s.index)
    out[s.isin(YES_VALUES)] = "Yes"
    out[s.isin(NO_VALUES)] = "No"
    return out


def _yes_no_counts(df: pd.DataFrame, column: str, title: str, key: str):
    if column not in df.columns:
        st.info(f"There is no data for {title}.")
        return
    raw = df[column].fillna("").astype(str).str.strip()
    if raw.eq("").all():
        st.info(f"There is no data for {title}.")
        return
    mapped = _normalize_yes_no(raw)
    counts = mapped.value_counts().reset_index()
    counts.columns = ["Response", "Count"]
    counts["Percent"] = (counts["Count"] / counts["Count"].sum() * 100).round(1)
    fig = px.pie(counts, names="Response", values="Count", hole=0.45, color="Response", color_discrete_sequence=PLOTLY_PALETTE, title=title)
    fig.update_traces(
        textinfo="percent",
        customdata=counts[["Count", "Percent"]].values,
        hovertemplate="<b>%{label}</b><br>Count: %{customdata[0]}<br>Share: %{customdata[1]}%<extra></extra>",
    )
    fig.update_layout(template="plotly_white", height=370, margin=dict(l=10, r=10, t=60, b=20), showlegend=True)
    st.plotly_chart(fig, width="stretch", key=key)


def _scholarship_subgroup_chart(df: pd.DataFrame, scholarship_col: str, attend_col: str, key: str):
    if scholarship_col not in df.columns:
        st.info("There is no scholarship data.")
        return
    scholarship_status = _normalize_yes_no(df[scholarship_col])
    subgroup = df[scholarship_status.eq("Yes")].copy()
    if subgroup.empty:
        st.info("No scholarship applicants were found in the file.")
        return
    if attend_col not in subgroup.columns:
        st.info("The file does not contain the follow-up question about participating without scholarship.")
        return
    attend_status = _normalize_yes_no(subgroup[attend_col])
    counts = attend_status.value_counts().reset_index()
    counts.columns = ["Response", "Count"]
    counts["Percent"] = (counts["Count"] / counts["Count"].sum() * 100).round(1)
    fig = px.pie(counts, names="Response", values="Count", hole=0.45, color="Response", color_discrete_sequence=PLOTLY_PALETTE, title="Among scholarship applicants: would still participate without scholarship?")
    fig.update_traces(
        textinfo="percent",
        customdata=counts[["Count", "Percent"]].values,
        hovertemplate="<b>%{label}</b><br>Count: %{customdata[0]}<br>Share within scholarship group: %{customdata[1]}%<extra></extra>",
    )
    fig.update_layout(template="plotly_white", height=370, margin=dict(l=10, r=10, t=60, b=20), showlegend=True)
    st.plotly_chart(fig, width="stretch", key=key)
    total_n = len(df)
    applied_n = len(subgroup)
    applied_pct = round(applied_n / total_n * 100, 1) if total_n else 0
    st.caption(f"{applied_n} of {total_n} applicants applied for scholarship ({applied_pct}%). This chart uses only the scholarship-applicant subgroup.")


def _distribution_chart(df: pd.DataFrame, column: str, title: str, color: str, key: str, top_n: int | None = None):
    s = _clean_series(df, column)
    if s.empty:
        st.info(f"There is no data for {column}.")
        return
    counts = s.value_counts().reset_index()
    counts.columns = [column, "Count"]
    if top_n:
        counts = counts.head(top_n)
    counts["Percent"] = (counts["Count"] / counts["Count"].sum() * 100).round(1)
    counts = counts.sort_values(["Count", column], ascending=[True, True])
    counts["Label"] = counts["Count"].astype(str) + " (" + counts["Percent"].astype(str) + "%)"
    height = max(360, min(900, 28 * len(counts) + 130))
    fig = px.bar(counts, x="Count", y=column, orientation="h", text="Label", title=title)
    fig.update_traces(
        marker_color=color,
        textposition="outside",
        cliponaxis=False,
        customdata=counts[["Percent"]].values,
        hovertemplate=f"<b>%{{y}}</b><br>Count: %{{x}}<br>Share: %{{customdata[0]}}%<extra></extra>",
    )
    fig.update_layout(template="plotly_white", height=height, margin=dict(l=20, r=60, t=60, b=20), yaxis_title="", xaxis_title="Applicants", showlegend=False)
    st.plotly_chart(fig, width="stretch", key=key)


def _program_mix_chart(df: pd.DataFrame, key: str):
    s = _clean_series(df, "Program")
    if s.empty:
        st.info("There is no data for Programme mix.")
        return
    counts = s.value_counts().reset_index()
    counts.columns = ["Program", "Count"]
    counts["Percent"] = (counts["Count"] / counts["Count"].sum() * 100).round(1)
    fig = px.pie(counts, names="Program", values="Count", hole=0.45, title="Study level / programme mix", color_discrete_sequence=PLOTLY_PALETTE)
    fig.update_traces(textinfo="percent", customdata=counts[["Count", "Percent"]].values, hovertemplate="<b>%{label}</b><br>Count: %{customdata[0]}<br>Share: %{customdata[1]}%<extra></extra>")
    fig.update_layout(template="plotly_white", height=370, margin=dict(l=20, r=20, t=60, b=20), legend=dict(orientation="v"))
    st.plotly_chart(fig, width="stretch", key=key)


def _age_range_chart(df: pd.DataFrame, key: str):
    if "Age" not in df.columns:
        st.info("There is no age data.")
        return
    ages = pd.to_numeric(df["Age"], errors="coerce").dropna()
    if ages.empty:
        st.info("There is no age data.")
        return
    bins = [0, 20, 25, 30, 35, 40, 200]
    labels = ["≤20", "21–25", "26–30", "31–35", "36–40", "41+"]
    grouped = pd.cut(ages, bins=bins, labels=labels, right=True).value_counts().reindex(labels).fillna(0).astype(int).reset_index()
    grouped.columns = ["Age range", "Count"]
    grouped["Percent"] = (grouped["Count"] / grouped["Count"].sum() * 100).round(1)
    fig = px.bar(grouped, x="Age range", y="Count", text="Count", title="Age range", color_discrete_sequence=[PLOTLY_PALETTE[1]])
    fig.update_traces(customdata=grouped[["Percent"]].values, hovertemplate="<b>%{x}</b><br>Count: %{y}<br>Share: %{customdata[0]}%<extra></extra>")
    fig.update_layout(template="plotly_white", height=360, margin=dict(l=20, r=20, t=60, b=20), showlegend=False)
    st.plotly_chart(fig, width="stretch", key=key)


def _country_map(df: pd.DataFrame, show_residence: bool, show_citizenship: bool, key: str):
    parts = []
    if show_residence and "Country of Residence" in df.columns:
        tmp = df[["Country of Residence"]].copy(); tmp.columns = ["country"]; tmp["type"] = "Residence"; parts.append(tmp)
    if show_citizenship and "Country of Citizenship" in df.columns:
        tmp = df[["Country of Citizenship"]].copy(); tmp.columns = ["country"]; tmp["type"] = "Citizenship"; parts.append(tmp)
    if not parts:
        st.info("Turn on residence and/or citizenship to show the map.")
        return
    merged = pd.concat(parts, ignore_index=True)
    merged["country"] = merged["country"].fillna("").astype(str).str.strip()
    merged = merged[merged["country"] != ""]
    if merged.empty:
        st.info("There is no country data to show on the map.")
        return
    counts = merged.groupby(["country", "type"]).size().reset_index(name="count")
    counts["Percent"] = (counts["count"] / counts["count"].sum() * 100).round(1)
    fig = px.choropleth(counts, locations="country", locationmode="country names", color="count", hover_name="country", hover_data={"type": True, "count": True, "Percent": True}, color_continuous_scale="Blues", title="Where applicants are from")
    fig.update_layout(height=500, template="plotly_white", margin=dict(l=20, r=20, t=60, b=20))
    st.plotly_chart(fig, width="stretch", key=key)


def _country_bar(df: pd.DataFrame, country_column: str, title: str, key: str):
    if country_column not in df.columns:
        st.info(f"There is no data for {title}.")
        return
    _distribution_chart(df, country_column, title, color=PLOTLY_PALETTE[3], key=key, top_n=20)


def _word_cloud(df: pd.DataFrame, columns: List[str], title: str, stopwords: set[str], key: str):
    values: List[str] = []
    for col in columns:
        if col in df.columns:
            values.extend(df[col].fillna("").astype(str).tolist())
    text = _tokenize_text(values, STOPWORDS.union(stopwords))
    if not text.strip():
        st.info(f"There is no text to show for {title}.")
        return
    wc = WordCloud(width=1400, height=560, background_color="white", collocations=False, stopwords=STOPWORDS.union(stopwords), colormap="viridis", prefer_horizontal=0.9).generate(text)
    fig, ax = plt.subplots(figsize=(13.5, 5.2))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title(title, fontsize=18, pad=12)
    st.pyplot(fig, clear_figure=True)


def render_dashboard(applicants_df: pd.DataFrame, reviewers_df: pd.DataFrame, shortlist_only: bool = True):
    st.markdown('<div class="step">', unsafe_allow_html=True)
    st.markdown("## Dashboard")
    st.markdown("<div class='explain'>This page gives the big picture before interview allocation: interview candidates, interviewer capacity, country distribution, study-level mix, and university background.</div>", unsafe_allow_html=True)

    planning = compute_planning_metrics(applicants_df, reviewers_df)
    applicants = max(planning["Applicants"], 1)
    reviewer_total = max(len(reviewers_df), 1)
    active_pct = planning["Active Interviewers"] / reviewer_total * 100 if reviewer_total else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Interview candidates", planning["Interview Candidates"], help="How many people are selected for interview.")
        _metric_subtext("Interview-required records")
    with c2:
        st.metric("Interview capacity", planning["Interview Capacity"], help="Total interview slots declared by active interviewers.")
        _metric_subtext("Declared interviewer slots")
    with c3:
        st.metric("Capacity gap", planning["Capacity Gap"], help="Positive means extra capacity; negative means not enough interview slots.")
        _metric_subtext("Capacity minus interview candidates")
    with c4:
        st.metric("Active interviewers", planning["Active Interviewers"], help="Only interviewers with Active = TRUE are used by the allocator.")
        _metric_subtext(f"{active_pct:.1f}% of interviewer table")

    st.markdown("### Applicant snapshot")
    display_cols = [c for c in ["Applicant ID", "Full Name", "Program", "University", "Field", "Gender", "Age", "Country of Residence", "Country of Citizenship", "Applied for scholarship?", "Graduate Track Applicant?", "Accessibility requirements?"] if c in applicants_df.columns]
    st.dataframe(make_streamlit_safe_df(applicants_df[display_cols]), width="stretch", height=300)

    st.markdown("### Geography")
    m1, m2 = st.columns([1, 1])
    with m1:
        show_residence = st.checkbox("Show country of residence", value=True, help="Counts applicants by where they currently live.")
    with m2:
        show_citizenship = st.checkbox("Show country of citizenship", value=True, help="Counts applicants by citizenship. You can show both.")
    _country_map(applicants_df, show_residence, show_citizenship, key="dashboard_country_map")

    cb1, cb2 = st.columns(2)
    with cb1:
        _country_bar(applicants_df, "Country of Residence", "Most frequent countries of residence", key="country_residence_bar")
    with cb2:
        _country_bar(applicants_df, "Country of Citizenship", "Most frequent countries of citizenship", key="country_citizenship_bar")

    st.markdown("### Applicant composition")
    g1, g2, g3 = st.columns(3)
    with g1:
        _program_mix_chart(applicants_df, key="dashboard_program_mix")
    with g2:
        _distribution_chart(applicants_df, "Gender", "Gender", color=PLOTLY_PALETTE[4], key="dashboard_gender_bar")
    with g3:
        _age_range_chart(applicants_df, key="dashboard_age_range")

    st.markdown("### Scholarship and application context")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        _yes_no_counts(applicants_df, "Applied for scholarship?", "Scholarship application", key="dashboard_scholarship_pie")
    with s2:
        _scholarship_subgroup_chart(applicants_df, "Applied for scholarship?", "Would still participate without scholarship?", key="dashboard_without_scholarship_subgroup")
    with s3:
        _yes_no_counts(applicants_df, "Graduate Track Applicant?", "Graduate Track applicants", key="dashboard_grad_track_pie")
    with s4:
        _yes_no_counts(applicants_df, "Previously applied to RAUN?", "Repeat applicants", key="dashboard_repeat_pie")

    st.markdown("### Universities and university background")
    g1, g2 = st.columns(2)
    with g1:
        _distribution_chart(applicants_df, "University", "All universities", color=PLOTLY_PALETTE[0], key="dashboard_universities_bar")
    with g2:
        _distribution_chart(applicants_df, "Field", "Fields / major areas", color=PLOTLY_PALETTE[2], key="dashboard_fields_bar")

    w1, w2 = st.columns(2)
    with w1:
        _word_cloud(applicants_df, ["University", "University (All)"], "University word cloud", stopwords=UNIVERSITY_STOPWORDS, key="university_cloud")
    with w2:
        _word_cloud(applicants_df, ["University Background Tags", "Field", "Field (All)", "Background Tags"], "University background / topic cloud", stopwords=FIELD_STOPWORDS, key="background_cloud")

    st.markdown('</div>', unsafe_allow_html=True)
