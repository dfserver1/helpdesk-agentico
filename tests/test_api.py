"""
Integration tests for the HelpDesk Copilot v12 REST API.
"""


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_ready(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


def test_register_login(client):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@helpdesk.ai",
            "password": "Password123!",
            "username": "second",
            "full_name": "Second User",
        },
    )
    assert r.status_code == 200
    assert r.json()["email"] == "second@helpdesk.ai"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "second@helpdesk.ai", "password": "Password123!"},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]
    assert login.json()["refresh_token"]


def test_me_requires_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me(client, auth_headers):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "api.test@helpdesk.ai"


def test_ticket_crud(client, auth_headers):
    # Create
    r = client.post(
        "/api/v1/tickets",
        headers=auth_headers,
        json={
            "title": "VPN not connecting",
            "description": "GlobalProtect fails with error 800 after update",
            "priority": "P2",
            "category": "Networking",
        },
    )
    assert r.status_code == 201, r.text
    ticket = r.json()
    assert ticket["ticket_number"].startswith("TK-")
    assert ticket["status"] == "OPEN"
    assert ticket["sla_due_at"] is not None

    ticket_id = ticket["id"]

    # Read
    r = client.get(f"/api/v1/tickets/{ticket_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["title"] == "VPN not connecting"

    # Update
    r = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        headers=auth_headers,
        json={"status": "RESOLVED"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "RESOLVED"
    assert r.json()["resolved_at"] is not None

    # List
    r = client.get("/api/v1/tickets", headers=auth_headers)
    assert r.status_code == 200
    assert any(t["id"] == ticket_id for t in r.json())

    # Events
    r = client.get(f"/api/v1/tickets/{ticket_id}/events", headers=auth_headers)
    assert r.status_code == 200
    types = [e["event_type"] for e in r.json()]
    assert "CREATED" in types


def test_ticket_not_found(client, auth_headers):
    r = client.get("/api/v1/tickets/999999", headers=auth_headers)
    assert r.status_code == 404


def test_memory_ingest(client, auth_headers):
    r = client.post(
        "/api/v1/memory/ingest",
        headers=auth_headers,
        json={
            "payload": {
                "issue": "Outlook crashes on calendar open",
                "resolution": "Clear cached shared calendars and rebuild OST",
                "priority": "P2",
            }
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "COMPLETED"


def test_memory_recall(client, auth_headers):
    r = client.post(
        "/api/v1/memory/recall?query=Outlook crash&top_k=3",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_admin_stats_forbidden_for_agent(client, auth_headers):
    r = client.get("/api/v1/admin/stats", headers=auth_headers)
    assert r.status_code == 403


def test_invalid_login(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@helpdesk.ai", "password": "wrongpass"},
    )
    assert r.status_code == 401