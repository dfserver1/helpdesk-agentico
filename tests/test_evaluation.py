"""
Unit tests for evaluation metrics (heuristic, no external services required).
"""

from evaluation.metrics import (
    evaluate_answer,
    evaluate_retrieval,
    score_context_faithfulness,
)


def test_retrieval_perfect():
    expected = ["vpn fix", "clear cache"]
    retrieved = ["vpn fix", "clear cache", "extra"]
    m = evaluate_retrieval(expected, retrieved)
    assert m["recall_at_k"] == 1.0
    assert abs(m["precision_at_k"] - 2 / 3) < 0.001


def test_retrieval_no_overlap():
    m = evaluate_retrieval(["printer jam"], ["vpn config"])
    assert m["recall_at_k"] == 0.0
    assert m["precision_at_k"] == 0.0


def test_faithfulness_grounded():
    context = ["Restart the printer spooler service and clear the print queue."]
    answer = "Restart the printer spooler service to fix the issue."
    m = score_context_faithfulness(answer, context)
    assert 0.0 < m["faithfulness"] <= 1.0
    assert m["mode"] == "heuristic"


def test_faithfulness_ungrounded():
    context = ["VPN configuration steps"]
    answer = "Reinstall the operating system completely."
    m = score_context_faithfulness(answer, context)
    assert m["faithfulness"] < 0.3


def test_answer_relevancy():
    m = evaluate_answer(
        question="How to reset password in Active Directory?",
        answer="Use the self-service portal to reset your Active Directory password.",
        context=["self-service portal reset password active directory"],
    )
    assert m["relevancy"] > 0.0
    assert "faithfulness" in m


def test_exact_match():
    m = evaluate_answer(
        question="test",
        answer="the answer",
        context=["the answer"],
        expected_answer="the answer",
    )
    assert m["exact_match"] == 1.0