import streamlit as st
from raun_interview_allocator import user_config as cfg
from raun_interview_allocator.shared_app import login_screen, main_app

st.set_page_config(page_title=cfg.APP_TITLE, page_icon="📋", layout="wide", initial_sidebar_state="expanded")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = cfg.DEFAULT_USERNAME

if not st.session_state.logged_in:
    login_screen()
else:
    main_app()
