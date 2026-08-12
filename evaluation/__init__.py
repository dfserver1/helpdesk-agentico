"""
Evaluation package for HelpDesk Enterprise Copilot.
"""

from evaluation.metrics import (
    evaluate_retrieval,
    evaluate_answer,
    score_context_faithfulness,
)
from evaluation.runner import EvaluationRunner, run_eval

__all__ = [
    "evaluate_retrieval",
    "evaluate_answer",
    "score_context_faithfulness",
    "EvaluationRunner",
    "run_eval",
]