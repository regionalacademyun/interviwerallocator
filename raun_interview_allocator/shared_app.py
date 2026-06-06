import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import user_config as cfg
from .dashboard_components import app_styles, render_dashboard
from .data_io import load_applicants, make_streamlit_safe_df, to_excel_bytes
from .google_sheets_io import read_google_sheet, write_google_sheet
from .interview_logic import (
    allocate_interviews,
    build_default_interviewers_df,
    compute_planning_metrics,
    filter_interview_pool,
    normalize_candidate_availability,
    normalize_interviewers_input,
    parse_interview_source,
)


def get_logo_path():
    for p in cfg.LOGO_CANDIDATES:
        if p.exists():
            return p
    return None


def login_screen():
    app_styles()
    left, right = st.columns([1, 1.4])
    with left:
        logo = get_logo_path()
        if logo:
            st.image(str(logo), width=120)
        st.markdown('<div class="hero">', unsafe_allow_html=True)
        st.title(cfg.APP_TITLE)
        st.caption(cfg.APP_SUBTITLE)
        st.markdown("<div class='explain'>Choose your name and enter the password to open the app. If your name is not listed, choose <b>New user / guest reviewer</b> and type your name.</div>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="step">', unsafe_allow_html=True)
        login_options = [""] + cfg.RAUN_TEAM_MEMBERS + [cfg.NEW_USER_LABEL]
        selected_user = st.selectbox("Choose your name", login_options, index=0)
        custom_user = ""
        if selected_user == cfg.NEW_USER_LABEL:
            custom_user = st.text_input("Type your full name")
        password = st.text_input("Password", type="password")
        if st.button("Login", type="primary", width="stretch"):
            final_user = custom_user.strip() if selected_user == cfg.NEW_USER_LABEL else selected_user
            if not final_user:
                st.warning("Please choose or type your name.")
            elif password == cfg.APP_PASSWORD:
                st.session_state.logged_in = True
                st.session_state.username = final_user
                st.rerun()
            else:
                st.error("Wrong password")
        st.markdown('</div>', unsafe_allow_html=True)
        st.stop()


def glossy_header(username: str):
    st.markdown(
        f"""
        <div class="hero">
            <h2 style="margin-bottom:0.25rem;">Hello {username.split()[0] if username else 'there'}!</h2>
            <div class="explain">This is the <b>interview allocation app</b>. It reads the RAUN interview-allocation sheet, derives the interview pool from Reviewer 1 and Reviewer 2 decisions, then allocates interviewers while favouring one of the two original reviewers wherever possible.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def ensure_state():
    defaults = {
        "source_mode": "Offline upload",
        "connected_sheet_ref": "",
        "connected_worksheet": "Sheet1",
        "local_service_account_file": "",
        "raw_input_df": None,
        "applicants_df": None,
        "review_source_df": None,
        "interview_pool_df": None,
        "interviewers_working_df": None,
        "interviewer_source_label": "Uniform RAUN interview baseline table",
        "candidate_availability_df": None,
        "intalloc_df": None,
        "intloads_df": None,
        "intexceptions_df": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def read_uploaded_raw(uploaded_file):
    if uploaded_file is None:
        return None
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, header=None)
    uploaded_file.seek(0)
    return pd.read_excel(uploaded_file, sheet_name=0, header=None)


def make_interviewer_template_bytes(interview_pool_df):
    template_df = build_default_interviewers_df(
        cfg.RAUN_TEAM_MEMBERS,
        interview_pool_df=interview_pool_df,
        use_uniform_baseline=True,
    )
    return to_excel_bytes({"Interviewer Availability Input": template_df})


def make_interview_capacity_plot(loads_df: pd.DataFrame):
    if loads_df is None or loads_df.empty:
        return None
    df = loads_df.copy().sort_values("Interview Assigned", ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["Reviewer Name"],
        y=df["Interview Capacity"],
        name="Declared interview capacity",
        marker_color="#BFDBFE",
        hovertemplate="<b>%{x}</b><br>Capacity: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["Reviewer Name"],
        y=df["Interview Assigned"],
        mode="markers+lines",
        name="Actually assigned",
        marker=dict(size=12, color="#8B5CF6", symbol="diamond"),
        line=dict(color="#8B5CF6", width=3),
        customdata=df[["Interview Capacity", "Remaining Interview Capacity", "Interview Utilization %"]].values,
        hovertemplate=(
            "<b>%{x}</b><br>Assigned: %{y}<br>Capacity: %{customdata[0]}<br>Remaining: %{customdata[1]}<br>Utilization: %{customdata[2]}%<extra></extra>"
        ),
    ))
    fig.update_layout(
        height=470,
        template="plotly_white",
        title="Interviewer capacity check: declared capacity and actual assignments",
        xaxis_title="Interviewer",
        yaxis_title="Number of interviews",
        margin=dict(l=20, r=20, t=70, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def _load_review_source_from_current_raw(decision_policy):
    raw = st.session_state.raw_input_df
    if raw is None or raw.empty:
        st.warning("Load the main Excel/Google Sheet first.")
        return
    parsed = parse_interview_source(raw, decision_policy=decision_policy)
    st.session_state.review_source_df = parsed
    st.session_state.interview_pool_df = filter_interview_pool(parsed)
    st.success(f"Review decisions parsed: {len(parsed)} applicants found; {len(st.session_state.interview_pool_df)} marked for interview.")


def main_app():
    app_styles()
    ensure_state()
    glossy_header(st.session_state.get("username", ""))

    st.markdown('<div class="step">', unsafe_allow_html=True)
    st.markdown("## Step 1 — Choose data source and load the interview-allocation sheet")
    st.markdown("<div class='explain'>Use the Excel/Google Sheet where data starts from row 3 and includes Reviewer 1, Reviewer 2, applicant details, both reviewer scoring blocks, and the two <b>Invitation to interview?</b> columns.</div>", unsafe_allow_html=True)

    source_mode = st.radio(
        "Input data source",
        ["Offline upload", "Connected Google Sheet"],
        horizontal=True,
        index=0 if st.session_state.source_mode == "Offline upload" else 1,
        help="Offline uses an uploaded Excel/CSV. Connected mode reads a live Google Sheet only after you paste the sheet address/ID.",
    )
    st.session_state.source_mode = source_mode

    if source_mode == "Offline upload":
        applicant_file = st.file_uploader("Upload interview-allocation Excel or CSV", type=["xlsx", "csv"], help="This is the sheet containing applicant details and the Reviewer 1/Reviewer 2 preselection assessment columns.")
        if applicant_file is not None:
            try:
                raw_df = read_uploaded_raw(applicant_file)
                st.session_state.raw_input_df = raw_df
                st.session_state.applicants_df = load_applicants(raw_df)
                st.success(f"Input file loaded: {len(st.session_state.applicants_df)} applicants detected for dashboard view.")
            except Exception as e:
                st.error(f"Could not read input file: {e}")
                st.markdown('</div>', unsafe_allow_html=True)
                return
    else:
        c1, c2 = st.columns([1.6, 1])
        with c1:
            sheet_ref = st.text_input("Google Sheet address or ID", value=st.session_state.connected_sheet_ref, help="Paste the Google Sheet URL or spreadsheet ID.")
        with c2:
            worksheet = st.text_input("Worksheet/tab name", value=st.session_state.connected_worksheet, help="Exact tab name, for example Sheet1 or Interview Allocation.")
        service_path = st.text_input("Optional local JSON key path for testing only", value=st.session_state.local_service_account_file, type="password", help="Leave blank when using Streamlit secrets.")
        st.session_state.connected_sheet_ref = sheet_ref
        st.session_state.connected_worksheet = worksheet
        st.session_state.local_service_account_file = service_path
        if st.button("Load live Google Sheet", type="primary", width="stretch"):
            try:
                raw_df = read_google_sheet(sheet_ref, worksheet, service_account_file=service_path or None)
                st.session_state.raw_input_df = raw_df
                st.session_state.applicants_df = load_applicants(raw_df)
                st.success(f"Live Google Sheet loaded: {len(st.session_state.applicants_df)} applicants detected for dashboard view.")
            except Exception as e:
                st.error(f"Could not read Google Sheet: {e}")
                st.markdown('</div>', unsafe_allow_html=True)
                return

    applicants_df = st.session_state.applicants_df
    st.markdown('</div>', unsafe_allow_html=True)
    if applicants_df is None or applicants_df.empty:
        st.info("Please load the interview-allocation sheet to continue.")
        return

    # Reuse the dashboard design from preselection, but the planning metrics here are only a general applicant overview.
    preview_reviewers = st.session_state.interviewers_working_df
    if preview_reviewers is None:
        preview_reviewers = build_default_interviewers_df(cfg.RAUN_TEAM_MEMBERS, interview_pool_df=pd.DataFrame(), use_uniform_baseline=False)
    render_dashboard(applicants_df, preview_reviewers.copy(), shortlist_only=True)

    st.markdown('<div class="step">', unsafe_allow_html=True)
    st.markdown("## Step 2 — Read Reviewer 1/2 assessment decisions")
    st.markdown("<div class='explain'>The app reads the two <b>Invitation to interview?</b> columns and applies the RAUN logic: Yes+Yes = Yes, No+No = No, Maybe+Maybe = Maybe, Maybe+Yes = Maybe+Yes, otherwise Maybe+No. The safe default is: <b>include everyone unless the combined decision is explicitly No</b>.</div>", unsafe_allow_html=True)
    decision_policy = st.selectbox(
        "Who should enter the interview allocation pool?",
        ["Exclude only explicit No+No", "Exclude No and No decision yet", "Yes + Maybe+Yes", "Yes only", "Yes + Maybe+Yes + Maybe"],
        index=0,
        help="Recommended default: include everyone unless both reviewer decisions produce an explicit No. This prevents accidental exclusion while reviews are incomplete.",
    )
    if st.button("Parse interview decisions from loaded sheet", type="primary", width="stretch"):
        _load_review_source_from_current_raw(decision_policy)

    if st.session_state.review_source_df is not None:
        all_review_df = st.session_state.review_source_df
        pool_df = st.session_state.interview_pool_df
        a, b, c, d = st.columns(4)
        a.metric("Applicants parsed", len(all_review_df), help="Rows with applicant names found in the sheet.")
        b.metric("Interview pool", len(pool_df), help="Applicants included under the selected decision policy.")
        c.metric("Not included", max(0, len(all_review_df) - len(pool_df)))
        d.metric("Decision policy", decision_policy)
        st.markdown("### Decision breakdown")
        if "Final Result- First review" in all_review_df.columns:
            breakdown = all_review_df["Final Result- First review"].fillna("No decision yet").astype(str).str.strip().replace({"": "No decision yet"}).value_counts().reset_index()
            breakdown.columns = ["First-review result", "Candidates"]
            st.dataframe(make_streamlit_safe_df(breakdown), width="stretch", height=220)
        st.markdown("### Reviewer coverage")
        reviewer_cols = [c for c in ["Preselection Reviewer 1", "Preselection Reviewer 2"] if c in all_review_df.columns]
        if reviewer_cols:
            reviewers_long = all_review_df[reviewer_cols].melt(value_name="Reviewer")["Reviewer"].fillna("").astype(str).str.strip()
            reviewers_long = reviewers_long[reviewers_long.ne("")]
            reviewer_summary = reviewers_long.value_counts().reset_index()
            reviewer_summary.columns = ["Reviewer", "Assigned preselection reviews in sheet"]
            st.dataframe(make_streamlit_safe_df(reviewer_summary), width="stretch", height=260)
        st.markdown("### Parsed decision preview")
        preview_cols = [c for c in ["Applicant ID", "Full Name", "Preselection Reviewer 1", "Preselection Reviewer 2", "Reviewer 1 Invitation", "Reviewer 2 Invitation", "Final Result- First review", "Interview Required", "Total points from Reviewer 1", "Total points from Reviewer 2", "Total points from both reviewers"] if c in all_review_df.columns]
        st.dataframe(make_streamlit_safe_df(all_review_df[preview_cols]), width="stretch", height=320)
        st.markdown("### Interview pool only")
        st.dataframe(make_streamlit_safe_df(pool_df[preview_cols]), width="stretch", height=320)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.interview_pool_df is None or st.session_state.interview_pool_df.empty:
        st.info("Parse interview decisions first. The interviewer allocation controls will appear after the interview pool is found.")
        return

    interview_pool_df = st.session_state.interview_pool_df
    if st.session_state.interviewers_working_df is None:
        st.session_state.interviewers_working_df = build_default_interviewers_df(cfg.RAUN_TEAM_MEMBERS, interview_pool_df=interview_pool_df, use_uniform_baseline=True)
        st.session_state.interviewer_source_label = "Uniform RAUN interview baseline table"

    st.markdown('<div class="step">', unsafe_allow_html=True)
    st.markdown("## Step 3 — Generate or load interviewer availability")
    st.markdown("<div class='explain'>This is the interview equivalent of the reviewer availability table. The app strictly respects <b>Active</b> and <b>Interview Capacity</b>. Available slots are optional.</div>", unsafe_allow_html=True)
    req_bytes = make_interviewer_template_bytes(interview_pool_df)
    planning = compute_planning_metrics(interview_pool_df, st.session_state.interviewers_working_df.copy())
    st.info(f"Planning view: {planning['Interview Candidates']} interview candidates. Current active interviewer capacity = {planning['Interview Capacity']}. Suggested average = {planning['Suggested Avg Interviews per Interviewer']} interviews per active interviewer.")
    st.download_button("Download interviewer availability template", data=req_bytes, file_name="interviewer_availability_template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

    c1, c2 = st.columns([1.2, 1.3])
    with c1:
        interviewer_file = st.file_uploader("Upload interviewer availability Excel or CSV", type=["xlsx", "csv"], key="int_upload")
    with c2:
        st.markdown("### Choose what to do")
        load_clicked = st.button("Use uploaded interviewer file", width="stretch")
        default_clicked = st.button("Use uniform RAUN interview baseline", width="stretch")
    if load_clicked:
        if interviewer_file is None:
            st.warning("Please upload the interviewer availability file first.")
        else:
            try:
                if interviewer_file.name.lower().endswith(".xlsx"):
                    new_df = pd.read_excel(interviewer_file)
                else:
                    new_df = pd.read_csv(interviewer_file)
                st.session_state.interviewers_working_df = normalize_interviewers_input(new_df)
                st.session_state.interviewer_source_label = f"Loaded from file: {interviewer_file.name}"
                st.success("The uploaded interviewer file is now the working interviewer table.")
            except Exception as e:
                st.error(f"Could not read interviewer file: {e}")
    if default_clicked:
        st.session_state.interviewers_working_df = build_default_interviewers_df(cfg.RAUN_TEAM_MEMBERS, interview_pool_df=interview_pool_df, use_uniform_baseline=True)
        st.session_state.interviewer_source_label = "Uniform RAUN interview baseline table"
        st.success("The uniform RAUN interview baseline table is active again.")

    st.info(f"Current interviewer table source: {st.session_state.interviewer_source_label}")
    editors_df = st.data_editor(
        st.session_state.interviewers_working_df.copy(),
        width="stretch",
        height=420,
        num_rows="dynamic",
        key="interviewer_availability_editor",
        column_config={
            "Reviewer Name": st.column_config.TextColumn("Interviewer Name", help="Interviewer full name. You may add new interviewers as extra rows."),
            "Active": st.column_config.CheckboxColumn("Active", help="If FALSE, this person receives no interviews."),
            "Interview Capacity": st.column_config.NumberColumn("Interview Capacity", min_value=0, step=1, help="Strict maximum number of interviews this person can take."),
            "Available Slots": st.column_config.TextColumn("Available Slots", help="Optional. Example: Mon AM, Tue PM. Leave blank if scheduling is manual."),
            "Background Tags": st.column_config.TextColumn("Background Tags", help="Soft matching helper only. Continuity with preselection reviewers has priority."),
            "Reviewer Notes": st.column_config.TextColumn("Reviewer Notes", help="Optional notes for the admin."),
        },
    )
    st.session_state.interviewers_working_df = normalize_interviewers_input(editors_df)
    interviewers_df = st.session_state.interviewers_working_df.copy()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="step">', unsafe_allow_html=True)
    st.markdown("## Step 4 — Optional candidate availability")
    st.markdown("<div class='explain'>This is optional. If not uploaded, the app assigns interviewers and the interviewer/candidate can coordinate by email. If uploaded, the app can also check simple slot overlap.</div>", unsafe_allow_html=True)
    cand_file = st.file_uploader("Optional candidate availability Excel/CSV", type=["xlsx", "csv"], key="candidate_availability")
    if cand_file is not None:
        try:
            if cand_file.name.lower().endswith(".xlsx"):
                cdf = pd.read_excel(cand_file)
            else:
                cdf = pd.read_csv(cand_file)
            st.session_state.candidate_availability_df = normalize_candidate_availability(cdf)
            st.success("Candidate availability loaded.")
            st.dataframe(make_streamlit_safe_df(st.session_state.candidate_availability_df), width="stretch", height=220)
        except Exception as e:
            st.error(f"Could not read candidate availability: {e}")
    else:
        st.caption("No candidate availability uploaded. Manual email coordination mode will be used.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="step">', unsafe_allow_html=True)
    st.markdown("## Step 5 — Generate interview allocation")
    st.markdown("<div class='explain'>The app tries to assign one of the two preselection reviewers as interviewer first. If both are unavailable, inactive, or full, it assigns another active interviewer with capacity and flags the exception.</div>", unsafe_allow_html=True)
    seed = st.number_input("Random seed", min_value=1, value=42, step=1, help="Use the same seed to reproduce the same allocation.")
    match_strength = st.selectbox("Background matching strength", ["Off", "Low", "Medium"], index=1, help="Soft bonus only. Continuity and capacity remain more important.")
    prefer_continuity = st.checkbox("Prefer one of the two preselection reviewers as interviewer", value=True)
    require_overlap = st.checkbox("Require candidate/interviewer availability overlap", value=False, help="Leave off unless you uploaded availability and want the app to enforce slot overlap.")

    planning = compute_planning_metrics(interview_pool_df, interviewers_df)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Interview candidates", planning["Interview Candidates"])
    p2.metric("Interview capacity", planning["Interview Capacity"])
    p3.metric("Capacity gap", planning["Capacity Gap"])
    p4.metric("Shortage", planning["Shortage"])

    tab_alloc, tab_stats, tab_sync = st.tabs(["Interview Allocation", "Workload Stats", "Google Sheet Output"])
    with tab_alloc:
        if st.button("Generate interview allocation", type="primary", width="stretch"):
            intalloc_df, intloads_df, intexceptions_df = allocate_interviews(
                interview_pool_df=interview_pool_df,
                interviewers_df=interviewers_df,
                candidate_availability_df=st.session_state.candidate_availability_df,
                seed=int(seed),
                match_strength=match_strength,
                prefer_preselection_reviewer=prefer_continuity,
                require_availability_overlap=require_overlap,
            )
            st.session_state.intalloc_df = intalloc_df
            st.session_state.intloads_df = intloads_df
            st.session_state.intexceptions_df = intexceptions_df
        if st.session_state.intalloc_df is not None:
            st.dataframe(make_streamlit_safe_df(st.session_state.intalloc_df), width="stretch", height=420)
            st.markdown("### Exceptions")
            if st.session_state.intexceptions_df is not None and not st.session_state.intexceptions_df.empty:
                st.dataframe(make_streamlit_safe_df(st.session_state.intexceptions_df), width="stretch", height=240)
            else:
                st.success("No interview exceptions.")
            out_excel = to_excel_bytes({
                "Interview Allocation": st.session_state.intalloc_df,
                "Interviewer Loads": st.session_state.intloads_df,
                "Interview Exceptions": st.session_state.intexceptions_df,
                "Interview Pool": interview_pool_df,
                "Parsed Review Decisions": st.session_state.review_source_df,
            })
            st.download_button("Download interview allocation Excel", out_excel, "raun_interview_allocation.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    with tab_stats:
        if st.session_state.intloads_df is None:
            st.info("Generate interview allocation first to see workload stats.")
        else:
            st.dataframe(make_streamlit_safe_df(st.session_state.intloads_df), width="stretch", height=300)
            fig = make_interview_capacity_plot(st.session_state.intloads_df)
            if fig is not None:
                st.plotly_chart(fig, width="stretch", key="interview_capacity_chart")
    with tab_sync:
        st.subheader("Write interview allocation results to Google Sheet")
        st.caption("Optional. Nothing is written unless you press a write button.")
        if st.session_state.intalloc_df is None:
            st.info("Generate an interview allocation first.")
        else:
            out_sheet_ref = st.text_input("Output Google Sheet address or ID", value=st.session_state.connected_sheet_ref)
            service_path_out = st.text_input("Optional local JSON key path", value=st.session_state.local_service_account_file, type="password", key="output_service_path")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Write allocation tab", width="stretch"):
                    try:
                        write_google_sheet(st.session_state.intalloc_df, out_sheet_ref, "Interview Allocation", service_account_file=service_path_out or None)
                        st.success("Interview Allocation written.")
                    except Exception as e:
                        st.error(f"Could not write allocation: {e}")
            with c2:
                if st.button("Write loads tab", width="stretch"):
                    try:
                        write_google_sheet(st.session_state.intloads_df, out_sheet_ref, "Interviewer Loads", service_account_file=service_path_out or None)
                        st.success("Interviewer Loads written.")
                    except Exception as e:
                        st.error(f"Could not write loads: {e}")
            with c3:
                if st.button("Write exceptions tab", width="stretch"):
                    try:
                        write_google_sheet(st.session_state.intexceptions_df, out_sheet_ref, "Interview Exceptions", service_account_file=service_path_out or None)
                        st.success("Interview Exceptions written.")
                    except Exception as e:
                        st.error(f"Could not write exceptions: {e}")
    st.markdown('</div>', unsafe_allow_html=True)
