"""
Streamlit frontend for HelpDesk Enterprise Copilot.

Run:
    streamlit run ui/app.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

import streamlit as st
from streamlit import session_state as ss

from ui.api_client import APIClient
from config.logging import get_logger

logger = get_logger("ui")

APP_TITLE = "HelpDesk Enterprise Copilot"

# Page setup ---------------------------------------------------------------
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
.stApp { background: #f6f8fb; }
[data-testid="stSidebar"] { background: #0f2537; color: white; }
[data-testid="stSidebar"] * { color: #e6edf3; }
h1, h2, h3 { color: #0b3d66; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --- Session helpers --------------------------------------------------------
def get_client() -> APIClient:
    if "api" not in ss:
        ss.api = APIClient()
    return ss.api


def _json(resp):
    """Safely parse a JSON response; returns {} on invalid/missing body."""
    if resp is None:
        return {}
    try:
        return resp.json()
    except Exception:
        return {}


def safe_call(fn, *args, **kwargs):
    """Run an async API call, surfacing errors succinctly."""
    import asyncio

    try:
        return asyncio.run(fn(*args, **kwargs))
    except Exception as e:
        st.error(f"API unreachable: {e}")
        return None


def logged_in() -> bool:
    return bool(ss.get("token"))


def _consume_oauth_token(provider: str):
    """Validate a manually pasted OAuth token and load the profile."""
    token = ss.get(f"oauth_token_input_{provider}", "")
    if not token:
        return
    me = safe_call(get_client().me, token)
    if me and me.status_code == 200:
        ss.token = token
        ss.user = _json(me)
        st.success(f"Signed in via {provider}")
    else:
        st.error("That token is not valid. Did you copy the full token from the login URL?")


def logout():
    for key in ("token", "user"):
        ss.pop(key, None)
    st.rerun()


# ─ Login / Register ------------------------------------------------------------
def auth_page():
    st.markdown(f"# {APP_TITLE}")
    st.caption("Enterprise AI Copilot with self-training memory engine")
    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary"):
                resp = safe_call(get_client().login, email, password)
                if resp and resp.status_code == 200:
                    data = _json(resp)
                    ss.token = data["access_token"]
                    me = safe_call(get_client().me, ss.token)
                    me_data = _json(me)
                    ss.user = me_data if me and me.status_code == 200 else {}
                    st.rerun()
                else:
                    st.error("Invalid credentials")

        st.markdown("---")
        st.caption("Or continue with:")
        for provider, label in (("google", "Google"), ("microsoft", "Microsoft 365")):
            if st.button(f"Sign in with {label}", key=f"oauth_{provider}", use_container_width=True):
                try:
                    redirect = st.query_params.get("redirect", "")
                    resp = safe_call(get_client().oauth_login_url, provider, redirect)
                    if resp and resp.status_code == 200:
                        # Store a lightweight marker so the callback page knows
                        # which provider started the flow.
                        ss[f"oauth_started_{provider}"] = True
                        import webbrowser

                        webbrowser.open(_json(resp)["authorize_url"])
                        st.info(
                            "Your browser should have opened the provider's sign-in page. "
                            "After approving, paste this page's token into the token box below."
                        )
                        st.text_input(
                            "Access token (from the URL after login)",
                            key=f"oauth_token_input_{provider}",
                            on_change=lambda p=provider: _consume_oauth_token(p),
                        )
                    else:
                        st.error("Provider unavailable — configure OAUTH in .env")
                except Exception as e:
                    st.error(f"OAuth start failed: {e}")

    # Fast-path: token returned via ?token= redirect from the API
    raw_token = st.query_params.get("token")
    if raw_token and ss.get("token") != raw_token:
        ss.token = raw_token
        me = safe_call(get_client().me, ss.token)
        me_data = _json(me)
        ss.user = me_data if me and me.status_code == 200 else {}
        st.rerun()

    with tab_register:
        with st.form("register"):
            email = st.text_input("Email (signup)")
            username = st.text_input("Username")
            full_name = st.text_input("Full name")
            password = st.text_input("Password (signup)", type="password")
            if st.form_submit_button("Create account"):
                resp = safe_call(
                    get_client().register,
                    {
                        "email": email,
                        "username": username,
                        "full_name": full_name,
                        "password": password,
                    },
                )
                if resp and resp.status_code == 200:
                    st.success("Account created! Log in to continue.")
                elif resp:
                    err = _json(resp).get("message", "Registration failed")
                    st.error(err)


# ─ Chat page -------------------------------------------------------------------
def chat_page():
    st.header("💬 AI Helpdesk Assistant")
    st.caption("Ask IT questions — grounded in your knowledge base and learned memory.")

    for msg in ss.get("chat_messages", []):
        role = "user" if msg["role"] == "user" else "assistant"
        with st.chat_message(role):
            st.markdown(msg["content"])

    prompt = st.chat_input("Describe your issue...")
    if prompt:
        st.chat_message("user").markdown(prompt)
        ss.setdefault("chat_messages", []).append({"role": "user", "content": prompt})

        session_id = ss.get("chat_session_id")
        resp = safe_call(get_client().chat, prompt, ss.token, session_id)
        if resp and resp.status_code == 200:
            data = _json(resp)
            ss.chat_session_id = data["session_id"]
            ss["chat_messages"] = ss.get("chat_messages", []) + [{"role": "assistant", "content": data["answer"]}]
            answer = data["answer"]
            with st.chat_message("assistant"):
                st.markdown(answer)
                if data.get("priority"):
                    st.caption(f"Priority: {data['priority']} | Category: {data.get('category')}")
                badges = []
                if data.get("used_connectors"):
                    badges.append("🔌 Connectors")
                if data.get("used_web_search"):
                    badges.append("🌐 Web search")
                if data.get("subagent_results"):
                    badges.append(f"🤖 {len(data['subagent_results'])} sub-results")
                if badges:
                    st.caption(" | ".join(badges))
                if data.get("sources"):
                    with st.expander(f"Sources ({len(data['sources'])})"):
                        for s in data["sources"]:
                            st.write(s)
        else:
            msg = (_json(resp).get("message") if resp else "") or "Assistant unavailable"
            with st.chat_message("assistant"):
                st.error(msg)


# ─ Tickets page ----------------------------------------------------------------
def tickets_page():
    st.title("🎫 Tickets")
    tab_list, tab_new = st.tabs(["My tickets", "Create ticket"])

    with tab_list:
        resp = safe_call(get_client().list_tickets, ss.token)
        if resp and resp.status_code == 200:
            tickets = _json(resp)
            if not tickets:
                st.info("No tickets yet — create one below.")
            for t in tickets:
                with st.expander(f"{t['ticket_number']} — {t['title']} [{t['status']}]"):
                    st.write(f"**Priority:** {t['priority']}  |  **SLA due:** {t.get('sla_due_at')}")
                    st.write(t["description"])

    with tab_new:
        with st.form("new_ticket"):
            title = st.text_input("Title")
            desc = st.text_area("Description")
            priority = st.selectbox("Priority", ["P1", "P2", "P3", "P4"], index=2)
            category = st.text_input("Category", "Technical Support")
            if st.form_submit_button("Create", type="primary"):
                resp = safe_call(
                    get_client().create_ticket,
                    {"title": title, "description": desc, "priority": priority, "category": category},
                    ss.token,
                )
                if resp and resp.status_code == 201:
                    st.success(f"Ticket created: {_json(resp)['ticket_number']}")
                elif resp:
                    st.error(_json(resp).get("message", "Creation failed"))


# ─ Self-training page -------------------------------------------------------------
def memory_page():
    st.title("🧠 Self-Training Memory")
    st.caption("Teach the agent continuously from enterprise metadata (issue → resolution).")
    admin_roles = ("agent", "manager", "admin")

    tab_ingest, tab_case, tab_recall = st.tabs(["Ingest Payload", "Case Study", "Recall"])

    with tab_ingest:
        st.markdown("Ingest an arbitrary metadata object including `issue` and `resolution`.")
        with st.form("ingest"):
            issue = st.text_input("Issue / Query")
            resolution = st.text_area("Resolution / Answer")
            priority = st.selectbox("Priority (ingest)", ["P1", "P2", "P3", "P4"], index=2)
            extra = st.text_area("Extra metadata (JSON, optional)", "")
            if st.form_submit_button("Teach the agent", type="primary"):
                payload = {"issue": issue, "resolution": resolution, "priority": priority}
                if extra.strip():
                    import json as _json

                    try:
                        payload.update(_json.loads(extra))
                    except Exception:
                        st.warning("Extra metadata is not valid JSON — ignored")
                resp = safe_call(get_client().ingest_payload, payload, ss.token)
                if resp and resp.status_code == 201:
                    st.success(f"Episodic memory stored (run #{_json(resp)['id']} {_json(resp)['status']})")
                elif resp:
                    st.error(_json(resp).get("message", "Ingest failed"))

    with tab_case:
        with st.form("case_study"):
            title = st.text_input("Case title")
            description = st.text_area("Symptom / description")
            resolution = st.text_area("Resolution steps")
            priority = st.selectbox("Priority (case)", ["P1", "P2", "P3", "P4"], index=2)
            category = st.text_input("Category", "Networking")
            tags = st.text_input("Tags (comma separated)")
            if st.form_submit_button("Store case study", type="primary"):
                resp = safe_call(
                    get_client().create_case_study,
                    {
                        "title": title,
                        "description": description,
                        "resolution": resolution,
                        "priority": priority,
                        "category": category,
                        "tags": [t.strip() for t in tags.split(",") if t.strip()],
                    },
                    ss.token,
                )
                if resp and resp.status_code == 201:
                    st.success("Case study stored")
                elif resp:
                    st.error(_json(resp).get("message", "Failed"))

    with tab_recall:
        query = st.text_input("Query to recall")
        top_k = st.slider("Top K", 1, 10, 3)
        if st.button("Search learned memory"):
            resp = safe_call(get_client().recall, query, ss.token, top_k)
            if resp and resp.status_code == 200:
                entries = _json(resp)
                if not entries:
                    st.info("No learned memory matched.")
                for e in entries:
                    with st.expander(
                        f"{e['memory_type']} — confidence {e['confidence']} (used {e['times_used']}×)"
                    ):
                        st.write(e["content"])
                        st.caption(f"Source: {e['source']} | {e['created_at']}")


# ─ Admin page --------------------------------------------------------------------
def admin_page():
    st.title("🛡️ Admin")
    resp = safe_call(get_client().admin_stats, ss.token)
    if resp and resp.status_code == 200:
        stats = _json(resp)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Tickets", stats.get("tickets_total", 0))
        c2.metric("Open", stats.get("tickets_open", 0))
        c3.metric("Users", stats.get("users", 0))
    elif resp:
        st.warning("Admin access required")


# ─ Router ------------------------------------------------------------------------
def main():
    get_client()

    if not logged_in():
        auth_page()
        return

    with st.sidebar:
        user = ss.get("user", {})
        st.markdown(f"**{user.get('full_name', 'User')}**")
        st.caption(user.get("email", ""))
        st.divider()
        page = st.radio("Navigation", ["Chat", "Tickets", "Self-Training", "Admin"])
        st.divider()
        if st.button("Sign out"):
            logout()

    if page == "Chat":
        chat_page()
    elif page == "Tickets":
        tickets_page()
    elif page == "Self-Training":
        memory_page()
    else:
        admin_page()


main()