import streamlit as st

CSS = """
<style>
.main .block-container {padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px;}
.raun-hero {border-radius: 24px; padding: 1.15rem 1.35rem; background: linear-gradient(135deg, #f5f8ff 0%, #ffffff 55%, #eef6ff 100%); border: 1px solid rgba(49,51,63,.12); margin-bottom: 1rem;}
.raun-card {border: 1px solid rgba(49,51,63,.14); border-radius: 18px; padding: 1rem 1.05rem; background: rgba(255,255,255,.96); box-shadow: 0 1px 2px rgba(16,24,40,.04); margin-bottom: .85rem;}
.raun-soft {border: 1px solid rgba(49,51,63,.10); border-radius: 16px; padding: .8rem .95rem; background: linear-gradient(135deg, rgba(238,246,255,.85), rgba(255,255,255,.98));}
.warn-box {border-left: 5px solid #d97706; background: rgba(245,158,11,.10); padding: .85rem 1rem; border-radius: 12px; margin: .6rem 0 1rem 0;}
.good-box {border-left: 5px solid #16a34a; background: rgba(34,197,94,.10); padding: .85rem 1rem; border-radius: 12px; margin: .6rem 0 1rem 0;}
.bad-box {border-left: 5px solid #dc2626; background: rgba(239,68,68,.10); padding: .85rem 1rem; border-radius: 12px; margin: .6rem 0 1rem 0;}
.small-muted {font-size: .85rem; color: rgba(49,51,63,.65);}
hr {margin-top: .7rem; margin-bottom: .7rem;}
</style>
"""

def apply_global_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
