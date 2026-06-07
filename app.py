from __future__ import annotations
import streamlit as st
from raun_reviewer_workspace.user_config import APP_PASSWORD, ALL_LOGIN_OPTIONS, NEW_USER_LABEL, DEFAULT_USERNAME
from raun_reviewer_workspace.styles import apply_global_style
from raun_reviewer_workspace.interview_app import render_interview_app

st.set_page_config(page_title="RAUN Interview Scoring App", page_icon="🎙️", layout="wide", initial_sidebar_state="expanded")
apply_global_style()

def login():
    if "int_logged_in" not in st.session_state:
        st.session_state.int_logged_in = False
    if "int_username" not in st.session_state:
        st.session_state.int_username = DEFAULT_USERNAME
    if st.session_state.int_logged_in:
        return st.session_state.int_username
    st.title("RAUN Login")
    selected = st.selectbox("Reviewer/interviewer name", ALL_LOGIN_OPTIONS, index=0)
    typed = st.text_input("Type your full name", value="") if selected == NEW_USER_LABEL else ""
    password = st.text_input("Password", type="password")
    if st.button("Login", type="primary"):
        username = typed.strip() if selected == NEW_USER_LABEL else selected
        if username and password == APP_PASSWORD:
            st.session_state.int_logged_in = True
            st.session_state.int_username = username
            st.rerun()
        else:
            st.error("Wrong credentials or missing username.")
    st.stop()

username = login()
with st.sidebar:
    st.markdown(f"**Logged in as:** {username}")
render_interview_app(username)
