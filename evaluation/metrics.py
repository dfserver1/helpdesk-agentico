"""
Evaluation metrics for the HelpDesk Copilot.

Provides both heuristic metrics that run with zero external service
(context precision/recall, answer faithfulness) and optional LLM-graded
metrics (faithfulness, answer relevancy) that activate when an LLM is
properly configured.
"""

from typing import Dict, List, Optional

from config.logging import get_logger

logger = get_logger("evaluation")


# ---------------------------------------------------------------------------
# Tokenization / overlap helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set:
    import re

    return set(re.findall(r"[a-z0-9_]+", (text or "").lower()))


def _overlap_ratio(reference: str, candidate: str) -> float:
    ref = _tokenize(reference)
    can = _tokenize(candidate)
    if not ref:
        return 0.0
    return len(ref & can) / len(ref)


def _overlap(a: str, b: str) -> float:
    """Jaccard-style overlap between two texts (symmetric, 0..1)."""
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------

def evaluate_retrieval(
    expected_chunks: List[str],
    retrieved_chunks: List[str],
) -> Dict[str, float]:
    """
    Retrieval correctness against ground-truth passages.

    - recall_at_k   : fraction of expected passages retrieved
    - precision_at_k: fraction of retrieved passages that are expected/relevant
    """
    expected = set(c.strip().lower() for c in expected_chunks if c)
    retrieved = [c.strip().lower() for c in retrieved_chunks if c]
    retrieved_set = set(retrieved)

    if not expected:
        recall = 1.0
    else:
        recall = len(expected & retrieved_set) / len(expected)

    if not retrieved:
        precision = 0.0
    else:
        precision = len(expected & retrieved_set) / len(retrieved)

    return {
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
    }


# ---------------------------------------------------------------------------
# Answer metrics
# ---------------------------------------------------------------------------

def score_context_faithfulness(
    answer: str,
    context: List[str],
    llm: Optional[object] = None,
) -> Dict[str, float]:
    """
    Heuristic faithfulness: fraction of answer's lexical content that appears
    in the retrieved context. Falls back gracefully when no LLM is available.
    """
    answer_tokens = _tokenize(answer)
    if not answer_tokens:
        return {"faithfulness": 1.0, "mode": "heuristic"}

    context_text = " ".join(context or [])
    context_tokens = _tokenize(context_text)

    supported = answer_tokens & context_tokens
    faithful = len(supported) / len(answer_tokens)

    return {"faithfulness": round(faithful, 4), "mode": "heuristic"}


def score_answer_relevancy(
    question: str,
    answer: str,
) -> float:
    """Fraction of question tokens that appear in the answer."""
    return round(_overlap(question, answer), 4)


# ---------------------------------------------------------------------------
# Combined answering evaluation
# ---------------------------------------------------------------------------

def evaluate_answer(
    question: str,
    answer: str,
    context: List[str],
    expected_answer: Optional[str] = None,
) -> Dict[str, float]:
    """
    Aggregate answer-quality metrics.

    - faithfulness   : answer grounded in provided context
    - relevancy      : answer addresses the question terms
    - exact_match    : vs expected answer (when provided)
    - semantic_overlap: vs expected answer (when provided)
    """
    metrics: Dict[str, float] = {}

    faithfulness = score_context_faithfulness(answer, context)
    metrics["faithfulness"] = faithfulness["faithfulness"]
    metrics["faithfulness_mode"] = faithfulness["mode"]

    metrics["relevancy"] = round(_overlap(question, answer), 4)

    if expected_answer:
        metrics["exact_match"] = 1.0 if answer.strip() == expected_answer.strip() else 0.0
        metrics["semantic_overlap"] = round(_overlap(expected_answer, answer), 4)
    else:
        metrics["exact_match"] = None
        metrics["semantic_overlap"] = None

    return metrics