"""
Interactive CLI for HelpDesk Enterprise Copilot.

Talks to the REST API (default) or runs the agent in-process (--local).

Usage:
    python scripts/run_cli.py                      # connect to http://localhost:8000
    python scripts/run_cli.py --base-url https://x --email … --password …
    python scripts/run_cli.py --local               # run agent directly (no server)

The CLI supports:
    - email/password login (or reuse a token)
    - chat with the agent (same endpoint the UI uses)
    - ticket approval decisions ("yes"/"no") when the agent asks
    - connector/web-search status and inline source badges
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui.api_client import APIClient  # noqa: E402

BANNER = r"""     _   _      _          _              ____
    | | | | ___| |__   ___| |_ __ ___  __|  _ \  ___ ___  ___
    | |_| |/ _ \ '_ \ / _ \ | '_ ` _ \/ _` | | | / __/ _ \/ __|
    |  _  |  __/ | | |  __/ | | | | | | (_| |_| | (_|  __/\__ \
    |_| |_|\___|_| |_|\___|_|_| |_| |_|\__,_|___/\___\___||___/
    HelpDesk Enterprise — Multithreaded + Connectors + OAuth
"""


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HelpDesk Copilot interactive CLI")
    p.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    p.add_argument("--email", default=os.getenv("HD_EMAIL"))
    p.add_argument("--password", default=os.getenv("HD_PASSWORD"))
    p.add_argument("--token", default=os.getenv("HD_TOKEN"))
    p.add_argument("--local", action="store_true", help="run the agent in-process")
    return p.parse_args()


def _need(prompt: str) -> str:
    value = ""
    while not value.strip():
        value = input(prompt).strip()
    return value


async def _login(client: APIClient, args) -> str:
    if args.token:
        print(f"[cli] using provided token (…{args.token[-8:]})")
        return args.token
    email = args.email or _need("Email: ")
    password = args.password or _need("Password: ")
    resp = await client.login(email, password)
    if resp.status_code != 200:
        print(f"[auth] login failed: {resp.status_code} {resp.text[:200]}")
        return ""
    return _json(resp).get("access_token", "")


def _json(resp):
    try:
        return resp.json()
    except Exception:
        return {}


def _show_badges(data: dict):
    badges = []
    if data.get("used_connectors"):
        badges.append("connectors")
    if data.get("used_web_search"):
        badges.append("web")
    if data.get("subagent_results"):
        badges.append(f"subagents={len(data['subagent_results'])}")
    if badges:
        print(f"[sources] {' + '.join(badges)}")
    src = data.get("sources") or []
    if src:
        print("[sources]")
        for s in src:
            name = s.get("document_name") or s.get("title") or "?"
            print(f"  - {name}")


async def _await_oauth(provider: str, client: APIClient) -> str:
    """Open the OAuth authorize URL in the browser and ask for the returned token."""
    resp = await client.oauth_login_url(provider)
    if resp.status_code != 200:
        print(f"[oauth] provider unavailable ({resp.status_code})")
        return ""
    url = _json(resp)["authorize_url"]
    print(f"[oauth] Open this URL in your browser:\n{url}\n")
    token = input("…After approving, paste the token from the redirect URL: ").strip()
    return token


async def _chat_loop(client: APIClient, token: str):
    session_id = None
    print("\nType your IT issue (help | status | logout | q to quit):")
    while True:
        try:
            message = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            return

        if message.lower() in {"q", "quit", "exit"}:
            print("Bye!")
            return
        if message.lower() in {"logout"}:
            print("[cli] logged out")
            return
        if message.lower() in {"status", "connectors"}:
            resp = await client.connector_status(token)
            if resp.status_code == 200:
                items = _json(resp).get("connectors", [])
                for c in items:
                    mark = "ON" if c.get("enabled") else "off"
                    cfg = "configured" if c.get("configured") else "not configured"
                    print(f"  [{mark:>4}] {c.get('label', c.get('name'))} ({cfg})")
            else:
                print(f"[connectors] HTTP {resp.status_code} {resp.text[:120]}")
            continue
        if message.lower() in {"help"}:
            print("Commands: status/connectors, logout, q to quit. Anything else = chat.")
            continue

        resp = await client.chat(message, token, session_id)
        if resp.status_code != 200:
            print(f"[api] HTTP {resp.status_code}: {resp.text[:300]}")
            continue
        data = _json(resp)
        session_id = data.get("session_id") or session_id
        print(f"\nAgent> {data['answer']}")
        if data.get("priority"):
            print(f"  (priority={data['priority']} | category={data.get('category')})")
        _show_badges(data)

        while data.get("needs_approval"):
            decision = input("[ticket] Approve ticket? (yes/no) > ").strip().lower()
            if decision in {"yes", "y", "approve"}:
                decision = "yes"
            elif decision in {"no", "n", "deny"}:
                decision = "no"
            else:
                print("  Reply yes or no.")
                continue
            resp = await client.decide_ticket(session_id, decision, token)
            data = _json(resp)
            print(f"\nAgent> {data.get('answer')}")


async def _run_remote(args):
    client = APIClient(base_url=args.base_url)
    try:
        print(BANNER)
        token = await _login(client, args)
        if not token:
            print("[cli] Could not authenticate. Try --email/--password or register via the UI.")
            return
        me = _json(await client.me(token))
        print(f"[auth] signed in as {me.get('email')} ({me.get('role')})")
        await _chat_loop(client, token)
    finally:
        await client.close()


def _run_local():
    """In-process mode: no server. Uses the API's own logic via httpx TestClient."""
    from fastapi.testclient import TestClient
    import asyncio

    from app.main import create_app
    from config.settings import get_settings
    from database.models import init_db

    print(BANNER)
    settings = get_settings()
    print(f"[local] engine initializing (LLM provider: {settings.LLM_PROVIDER})")
    asyncio.run(init_db())

    app = create_app()
    client = TestClient(app)

    # Auto-register + login a fixture user so the CLI flows work immediately.
    email = "cli@example.com"
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "username": "cli", "full_name": "CLI User", "password": "cli12345"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "cli12345"})
    token = _json(r)["access_token"]
    print(f"[auth] signed in as {email}")

    session_id = None
    print("\nType your IT issue (status | q to quit):")
    while True:
        try:
            message = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            return
        if message.lower() in {"q", "quit", "exit"}:
            print("Bye!")
            return
        if message.lower() in {"status", "connectors"}:
            r = client.get("/api/v1/connectors/status", headers={"Authorization": f"Bearer {token}"})
            for c in _json(r).get("connectors", []):
                print(f"  [{'ON' if c.get('enabled') else 'off':>4}] {c.get('label')} "
                      f"({'configured' if c.get('configured') else 'not configured'})")
            continue
        r = client.post(
            "/api/v1/chat",
            json={"message": message, "session_id": session_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        data = _json(r)
        session_id = data.get("session_id") or session_id
        print(f"\nAgent> {data['answer']}")
        if data.get("priority"):
            print(f"  (priority={data['priority']} | category={data.get('category')})")
        _show_badges(data)
        while data.get("needs_approval"):
            decision = input("[ticket] Approve ticket? (yes/no) > ").strip().lower() or "yes"
            r = client.post(
                f"/api/v1/chat/{session_id}/decide",
                params={"decision": "yes" if decision.startswith("y") else "no"},
                headers={"Authorization": f"Bearer {token}"},
            )
            data = _json(r)
            print(f"\nAgent> {data.get('answer')}")


def main():
    args = _parse()
    if args.local:
        _run_local()
    else:
        asyncio.run(_run_remote(args))


if __name__ == "__main__":
    main()