from __future__ import annotations
import base64
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .assessment_logic import INTERVIEW_FIELDS, INTERVIEW_OPTIONS_1_TO_5, INTERVIEW_GUIDANCE, interview_total, interview_band, final_band
from .dashboard_components import render_dashboard, assigned_filter
from .data_io import read_tabular_file, to_excel_bytes, update_candidate, make_streamlit_safe_df
from .document_tools import uploaded_files_to_docs, load_local_pdf_documents
from .pdf_export import candidate_assessment_pdf, candidate_assessment_docx
from .styles import apply_global_style
from .user_config import ADMIN_USERS, APPLICANT_DOCS_DIR, SAMPLE_APPLICANT_DOCS_DIR
from .google_sheets_io import write_dataframe_new_worksheet

SESSION_DF_KEY = "int_df"
SESSION_RAW_KEY = "int_raw_df"
SESSION_META_KEY = "int_meta"

INT_COL_MAP = {
    "motivation": "Interview Motivation",
    "international": "Interview International",
    "research": "Interview Research",
    "professionalism": "Interview Professionalism",
    "respect_diversity": "Interview Respect Diversity",
    "communication_english": "Interview Communication English",
    "teamwork": "Interview Teamwork",
    "planning_organization": "Interview Planning Organization",
    "availability": "Interview Availability",
    "un_knowledge": "Interview UN Knowledge",
}

def _init_session():
    for key in [SESSION_DF_KEY, SESSION_RAW_KEY, SESSION_META_KEY]:
        if key not in st.session_state:
            st.session_state[key] = None

def load_data_panel():
    st.markdown("### Step 1 - Load interview assessment data")
    mode = st.radio("Data mode", ["Offline upload", "Connected Google Sheet"], horizontal=True, key="int_data_mode")
    if mode == "Offline upload":
        uploaded = st.file_uploader("Upload RAUN interview Excel/CSV or pre-selection export", type=["xlsx", "xlsm", "xls", "csv"], key="int_file")
        if uploaded and st.button("Read uploaded file", type="primary", key="int_read_upload"):
            raw, df, meta = read_tabular_file(uploaded)
            # Keep everyone except explicit No, following operational rule.
            if "Interview Required" in df.columns:
                df = df[df["Interview Required"].astype(str).str.strip().ne("No")].reset_index(drop=True)
            st.session_state[SESSION_RAW_KEY] = raw
            st.session_state[SESSION_DF_KEY] = df
            st.session_state[SESSION_META_KEY] = meta
            st.success(f"Loaded {len(df)} interview-pool applicants.")
    else:
        st.info("This mode reads only after you click the button. It does not write unless you explicitly export/write later.")
        url = st.text_input("Google Sheet URL or ID", key="int_sheet_url")
        tab = st.text_input("Worksheet/tab name", value="Reviewer Workspace Export", key="int_sheet_tab")
        json_path = st.text_input("Optional local service-account JSON path", value="", key="int_json_path")
        if st.button("Read Google Sheet", type="primary", key="int_read_gs"):
            try:
                from .google_sheets_io import read_worksheet_as_records
                loaded = read_worksheet_as_records(url, tab, json_path)
                # If this is already the clean export, use directly. Otherwise normalize through parser from values.
                if "Full Name" in loaded.columns and "Applicant ID" in loaded.columns:
                    df = make_streamlit_safe_df(loaded)
                else:
                    from .data_io import normalize_assessment_dataframe
                    df = normalize_assessment_dataframe(loaded, {})
                if "Interview Required" in df.columns:
                    df = df[df["Interview Required"].astype(str).str.strip().ne("No")].reset_index(drop=True)
                st.session_state[SESSION_DF_KEY] = df
                st.session_state[SESSION_META_KEY] = {"source_name": url, "worksheet": tab}
                st.success(f"Loaded {len(df)} applicants from Google Sheet.")
            except Exception as e:
                st.error(f"Could not read Google Sheet: {e}")

def candidate_detail_card(candidate: dict):
    st.markdown("### Candidate details")
    core = ["Applicant ID", "Full Name", "Email", "Program", "University", "Field", "Age", "Country of Residence", "Country of Citizenship", "Interviewer", "Derived First Review Result", "Total points from both reviewers"]
    for k in core:
        v = str(candidate.get(k, "")).strip()
        if v:
            st.markdown(f"**{k}:** {v}")
    with st.expander("Full Excel row / all candidate fields", expanded=True):
        show_cols = list(candidate.keys())
        full_rows = [{"Field": c, "Value": "" if pd.isna(candidate.get(c, "")) else candidate.get(c, "")} for c in show_cols]
        st.dataframe(pd.DataFrame(full_rows), hide_index=True, use_container_width=True)

def _embed_pdf_bytes(data: bytes, height: int = 680):
    b64 = base64.b64encode(data).decode("utf-8")
    st.markdown(f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}" type="application/pdf"></iframe>', unsafe_allow_html=True)


def document_panel(candidate: dict) -> tuple[str, list]:
    st.markdown("### Application PDF documents")
    uploaded_pdfs = st.file_uploader("Upload candidate/application PDFs", type=["pdf"], accept_multiple_files=True, key="int_pdf_upload")
    docs = []
    if uploaded_pdfs:
        docs.extend(uploaded_files_to_docs(uploaded_pdfs, candidate, extract_text=True))
    local_paths = []
    for root in [APPLICANT_DOCS_DIR, SAMPLE_APPLICANT_DOCS_DIR]:
        if root.exists():
            local_paths.extend(root.rglob("*.pdf"))
    if local_paths:
        docs.extend(load_local_pdf_documents(local_paths, candidate, extract_text=False))
    docs = sorted(docs, key=lambda d: d.match_score, reverse=True)
    if not docs:
        st.info("No PDFs uploaded or found in data/applicant_documents.")
        return "", docs
    labels = [f"{d.name} - match {d.match_score:.0f}%" for d in docs]
    choice = st.selectbox("Matched / available documents", labels, key=f"int_doc_choice_{candidate.get('Applicant ID')}")
    doc = docs[labels.index(choice)]
    data = b""; pdf_text = ""
    if doc.bytes_data:
        data = doc.bytes_data; pdf_text = doc.extracted_text or ""
    elif doc.path:
        data = Path(doc.path).read_bytes()
        cache_key = f"int_pdf_extract_{doc.path}"
        if cache_key not in st.session_state:
            from .document_tools import extract_pdf_text_from_path, build_document_checklist
            text, pages = extract_pdf_text_from_path(doc.path)
            st.session_state[cache_key] = {"text": text, "pages": pages, "checklist": build_document_checklist(text)}
        cached = st.session_state[cache_key]
        pdf_text = cached.get("text", "")
        doc.page_count = cached.get("pages", 0); doc.checklist = cached.get("checklist")
    if data:
        st.download_button("Download selected PDF", data=data, file_name=doc.name, mime="application/pdf", use_container_width=True, key=f"int_download_doc_{candidate.get('Applicant ID')}_{doc.name}")
        with st.expander("View selected PDF inside the app", expanded=True):
            _embed_pdf_bytes(data, height=720)
    st.info(f"PDF text extracted for reviewer context: {'Yes' if pdf_text.strip() else 'No'}. Extracted characters: {len(pdf_text):,}. Pages detected: {doc.page_count or 'unknown'}.")
    if pdf_text:
        with st.expander("Extracted PDF text preview", expanded=False):
            st.text_area("Extracted text", pdf_text[:30000], height=260, key=f"int_pdf_text_{candidate.get('Applicant ID')}")
    return pdf_text, docs

def _score_band_50(score) -> str:
    try: x = float(score)
    except Exception: return "Not scored"
    if x >= 41: return "Highly recommended"
    if x >= 31: return "Recommended"
    if x >= 21: return "Moderately recommended"
    return "Not recommended"


def _interview_form(candidate: dict) -> dict:
    updates = {}
    st.markdown("### Interview scoring form")
    with st.expander("Interview guidance", expanded=False):
        st.markdown("The interview evaluation total is 50 points. All 10 criteria are scored from 1 to 5. The interview should assess suitability for RAUN, not only UN knowledge.")
        for key, label in INTERVIEW_FIELDS:
            st.markdown(f"**{label}**: {INTERVIEW_GUIDANCE.get(key, '')}")
    option_labels = ["Not scored yet"] + [str(x) for x in INTERVIEW_OPTIONS_1_TO_5]
    numeric_scores = []
    criteria_names = []
    for key, label in INTERVIEW_FIELDS:
        col = INT_COL_MAP[key]
        raw = str(candidate.get(col, "")).strip()
        current_label = "Not scored yet"
        try:
            f = float(raw)
            if f in INTERVIEW_OPTIONS_1_TO_5:
                current_label = str(f)
            elif raw:
                f = min(INTERVIEW_OPTIONS_1_TO_5, key=lambda x: abs(x-f)); current_label = str(f)
        except Exception:
            pass
        chosen = st.selectbox(label, options=option_labels, index=option_labels.index(current_label), help=INTERVIEW_GUIDANCE.get(key, ""), key=f"int_{key}_{candidate.get('Applicant ID')}")
        updates[col] = "" if chosen == "Not scored yet" else float(chosen)
        if updates[col] != "":
            numeric_scores.append(float(updates[col])); criteria_names.append(label[:22])
    complete = len(numeric_scores) == len(INTERVIEW_FIELDS)
    if complete:
        total = sum(numeric_scores)
        updates["Interview Total"] = total
        updates["Interview Recommended"] = interview_band(total)
        st.metric("Live interview total", f"{total:.1f} / 50", updates["Interview Recommended"])
    else:
        updates["Interview Total"] = ""
        updates["Interview Recommended"] = "Not scored"
        st.warning(f"Interview score incomplete: {len(numeric_scores)} of {len(INTERVIEW_FIELDS)} criteria scored. No interview total will be written until all criteria are scored.")
    updates["Interview Top5"] = "Yes" if st.checkbox("Interview top-5?", value=str(candidate.get("Interview Top5", "")).casefold().startswith("yes"), key=f"int_top5_{candidate.get('Applicant ID')}") else "No"
    updates["Interview Comment"] = st.text_area("Interview comment / recommendation", value=str(candidate.get("Interview Comment", "")), height=150, key=f"int_comment_{candidate.get('Applicant ID')}")
    if complete:
        try: pre_total = float(candidate.get("Total points from both reviewers") or 0)
        except Exception: pre_total = 0
        final_total = pre_total + total
        updates["Final Total"] = final_total
        updates["Final Decision"] = final_band(final_total)
        st.metric("Final combined total", f"{final_total:.1f}", updates["Final Decision"])
    else:
        updates["Final Total"] = ""; updates["Final Decision"] = "Not scored"
    st.markdown("### Scoring graphics and bands")
    st.info(f"Interview band: {_score_band_50(updates.get('Interview Total',''))}")
    if numeric_scores:
        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(r=numeric_scores + [numeric_scores[0]], theta=criteria_names + [criteria_names[0]], fill='toself', name='Interview scores'))
        fig.update_layout(height=420, margin=dict(l=30,r=30,t=40,b=30), polar=dict(radialaxis=dict(visible=True, range=[0,5])), showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
    return updates

def render_interview_app(username: str):
    apply_global_style()
    _init_session()
    st.markdown('<div class="raun-hero"><h2>RAUN Interview Scoring App</h2><div class="small-muted">Interview scoring, recommendations, PDF summaries, and final export.</div></div>', unsafe_allow_html=True)
    load_data_panel()
    df = st.session_state.get(SESSION_DF_KEY)
    if df is None or df.empty:
        st.stop()
    is_admin = username in ADMIN_USERS
    admin_view_enabled = st.sidebar.checkbox("Admin tools enabled", value=is_admin, disabled=not is_admin, key="int_admin_tools")
    reviewer_for_view = username
    admin_view = False
    if is_admin and admin_view_enabled:
        reviewers = sorted([r for r in set(df.get("Interviewer", pd.Series(dtype=str)).astype(str).str.strip()) if r and r.lower() != "nan" and r != username])
        reviewer_for_view = st.sidebar.selectbox("Interviewer filter", [username, "All interviewers"] + reviewers, index=0, key="int_admin_reviewer")
    if reviewer_for_view == "All interviewers":
        view_df = df.copy(); admin_view = True
    else:
        view_df = assigned_filter(df, reviewer_for_view, "interview", False)
    section = st.radio("Workspace section", ["Dashboard", "Interview workspace", "Export"], horizontal=True, key="int_active_section")
    if section == "Dashboard":
        render_dashboard(df, reviewer_for_view if reviewer_for_view != "All interviewers" else username, "interview", admin_view)
    elif section == "Interview workspace":
        if view_df.empty:
            st.warning("No interview applicants assigned to this interviewer.")
        else:
            labels = [f"{int(r['Applicant ID'])} - {r['Full Name']} ({r.get('University','')})" for _, r in view_df.iterrows()]
            chosen = st.selectbox("Choose interview applicant", labels, key="int_candidate_select")
            applicant_id = int(chosen.split(" - ")[0])
            candidate = df.loc[df["Applicant ID"].astype(str) == str(applicant_id)].iloc[0].to_dict()
            left, right = st.columns([1.05, 1.25])
            with left:
                candidate_detail_card(candidate)
                pdf_text, docs = document_panel(candidate)
            with right:
                if not admin_view and str(candidate.get("Interviewer", "")).strip() not in {"", username}:
                    st.warning("You are not listed as the interviewer for this candidate. Admin view is required to edit.")
                updates = _interview_form(candidate)
                if st.button("Save interview assessment in session", type="primary", key=f"int_save_{applicant_id}"):
                    new_df = update_candidate(df, applicant_id, updates)
                    st.session_state[SESSION_DF_KEY] = new_df
                    st.success("Saved in session. Use Export to download the updated Excel, or write to a Google Sheet export tab.")
                    st.rerun()
                report_candidate = candidate.copy()
                report_candidate.update(updates if 'updates' in locals() else {})
                pdf_bytes = candidate_assessment_pdf(report_candidate, mode="interview")
                docx_bytes = candidate_assessment_docx(report_candidate, mode="interview")
                dl1, dl2 = st.columns(2)
                with dl1:
                    st.download_button("Download candidate PDF report", pdf_bytes, file_name=f"RAUN_interview_{candidate.get('Full Name','candidate')}.pdf", mime="application/pdf", use_container_width=True, key=f"int_pdf_{applicant_id}")
                with dl2:
                    st.download_button("Download candidate DOCX report", docx_bytes, file_name=f"RAUN_interview_{candidate.get('Full Name','candidate')}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True, key=f"int_docx_{applicant_id}")
    elif section == "Export":
        st.markdown("### Export")
        bytes_xlsx = to_excel_bytes({
            "Interview Assessment Sheet": df,
            "Interview Decisions": view_df,
        })
        st.download_button("Download interview assessment workbook", bytes_xlsx, file_name="RAUN_interview_assessment_export.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        with st.expander("Optional: write clean interview export to Google Sheet"):
            url = st.text_input("Google Sheet URL or ID", key="int_write_url")
            tab = st.text_input("Export worksheet name", value="Interview Assessment Export", key="int_write_tab")
            json_path = st.text_input("Optional local service-account JSON path", value="", key="int_write_json")
            if st.button("Write interview export tab", key="int_write_button"):
                try:
                    write_dataframe_new_worksheet(url, tab, df, json_path)
                    st.success("Export tab written successfully. The original tab was not overwritten.")
                except Exception as e:
                    st.error(f"Could not write Google Sheet export: {e}")
