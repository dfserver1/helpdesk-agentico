"""
Regression tests for security fixes: privilege escalation and auth hardening.
"""


def test_register_cannot_escalate_role(client):
    """A caller cannot request a privileged role at registration."""
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "escalator@helpdesk.ai",
            "password": "Password123!",
            "username": "escalator",
            "full_name": "Escalation Attempt",
            "role": "admin",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "escalator@helpdesk.ai", "password": "Password123!"},
    )
    token = login.json()["access_token"]
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.json()["role"] == "user"
    assert me.json()["is_superuser"] is False


def test_register_ignores_extra_role_field(client):
    """A role field smuggled into the payload is ignored (not honored)."""
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "strictrole@helpdesk.ai",
            "password": "Password123!",
            "username": "strictrole",
            "full_name": "Strict Role User",
            "role": "superadmin",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"