"""
End-to-end tests for the PRODUCTION ticket path: chat -> human approval ->
persistent ticket. This is the flow that was previously "demo-only": a bug in
it made every test pass while no real ticket was ever created.

The agent's LLM/retrieval nodes are monkeypatched (deterministic fakes) so the
graph is exercised end-to-end through the real checkpointer, interrupt/resume
and ticket backend, without needing API keys or network access.
"""

import pytest

import agent.graph as graph_mod


# ---------------------------------------------------------------------------
# Deterministic node fakes (route: classify -> retrieve -> grade ->
# generate_answer -> draft -> approval_gate)
# ---------------------------------------------------------------------------

def _fake_classify(state):
    return {
        "priority": "P2",
        "category": "Network",
        "sla_response_time": "4h",
        "classification_reasoning": "e2e mock",
    }


def _fake_retrieve(state):
    return {
        "documents": [],
        "query": state.get("query") or state["user_input"],
        "retrieved_chunks": 0,
        "last_confidence": 0.0,
    }


def _fake_grade(state):
    return {"is_relevant": True, "retrieval_retries": state.get("retrieval_retries", 0)}


def _fake_generate(state):
    return {
        "solution": "No KB answer; escalating for human assistance.",
        "resolved": False,
        "needs_human": True,
    }


@pytest.fixture
def mocked_graph(monkeypatch):
    """Compile the graph with deterministic nodes and no cached agent."""
    monkeypatch.setattr(graph_mod, "classify_node", _fake_classify)
    monkeypatch.setattr(graph_mod, "retrieve_node", _fake_retrieve)
    monkeypatch.setattr(graph_mod, "grade_node", _fake_grade)
    monkeypatch.setattr(graph_mod, "generate_answer_node", _fake_generate)
    monkeypatch.setattr(graph_mod, "_agent", None)
    yield
    # Force the next graph build to use the real node functions.
    graph_mod._agent = None


def _list_ticket_numbers(client, headers):
    resp = client.get("/api/v1/tickets", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_chat_approval_creates_real_ticket(client, auth_headers, mocked_graph):
    """Approve -> ticket persisted, visible via /tickets, with real fields."""
    resp = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "VPN is broken for all users since the update"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_approval"] is True
    assert data["decision_prompt"] is not None
    assert data["ticket_number"] is None
    assert data["category"] == "Network"
    session_id = data["session_id"]

    resp2 = client.post(
        f"/api/v1/chat/{session_id}/decide?decision=yes",
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["needs_approval"] is False
    assert d2["ticket_error"] is None
    assert d2["ticket_number"] and d2["ticket_number"].startswith("TK-")
    assert d2["ticket_status"] == "OPEN"

    tickets = _list_ticket_numbers(client, auth_headers)
    numbers = [t["ticket_number"] for t in tickets]
    assert d2["ticket_number"] in numbers
    created = next(t for t in tickets if t["ticket_number"] == d2["ticket_number"])
    # The classifier's category must survive to the persisted ticket (A4).
    assert created["category"] == "Network"
    assert created["priority"] == "P2"

    # Audit event must exist (CREATED) for the ticket.
    ev = client.get(
        f"/api/v1/tickets/{created['id']}/events", headers=auth_headers
    )
    assert ev.status_code == 200
    assert any(e["event_type"] == "CREATED" for e in ev.json())


def test_chat_denial_does_not_create_ticket(client, auth_headers, mocked_graph):
    """decide=no must inform the user and create NO ticket."""
    before = len(_list_ticket_numbers(client, auth_headers))

    resp = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "Printer offline in accounting"},
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    resp2 = client.post(
        f"/api/v1/chat/{session_id}/decide?decision=no",
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["ticket_number"] is None
    assert "assist" in d2["answer"].lower() or "notified" in d2["answer"].lower()

    after = len(_list_ticket_numbers(client, auth_headers))
    assert after == before


def test_decide_requires_pending_approval(client, auth_headers, mocked_graph):
    """A second decide on an already-finished thread must fail loudly (M2)."""
    resp = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "Keyboard not detected"},
    )
    session_id = resp.json()["session_id"]

    # Resolve the pending approval.
    r1 = client.post(
        f"/api/v1/chat/{session_id}/decide?decision=no", headers=auth_headers
    )
    assert r1.status_code == 200

    # Resuming again is not valid: no pending approval left.
    r2 = client.post(
        f"/api/v1/chat/{session_id}/decide?decision=yes", headers=auth_headers
    )
    assert r2.status_code == 400
    assert "pending" in r2.json().get("message", "").lower()

    # An invalid decision value is also rejected.
    resp3 = client.post(
        "/api/v1/chat",
        headers=auth_headers,
        json={"message": "Another issue"},
    )
    sid3 = resp3.json()["session_id"]
    r3 = client.post(
        f"/api/v1/chat/{sid3}/decide?decision=maybe", headers=auth_headers
    )
    assert r3.status_code == 400
