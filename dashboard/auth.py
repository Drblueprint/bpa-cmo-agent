"""Shared-password gate. One password, set in Streamlit secrets, no user accounts."""
from __future__ import annotations

import streamlit as st


def require_password() -> None:
    """Block rendering until the user enters the correct shared password.

    Sets st.session_state['authenticated'] on success. Call this as the very
    first line of the Streamlit app, after st.set_page_config.
    """
    if st.session_state.get("authenticated"):
        return

    st.title("BPA CMO Dashboard")
    pw = st.text_input("Password", type="password")
    if not pw:
        st.stop()

    expected = st.secrets.get("DASHBOARD_PASSWORD", "")
    if pw == expected and expected != "":
        st.session_state["authenticated"] = True
        st.rerun()
    else:
        st.error("Incorrect password.")
        st.stop()
