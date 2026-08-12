"""
Evaluation runner: execute the full RAG/agent pipeline against a labeled
test set and emit per-case + aggregate scores.

Interfaces with the RAG pipeline directly, so it works in both local
(hourglass) and cloud environments.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config.logging import get_logger
from evaluation.metrics import evaluate_answer, evaluate_retrieval

logger = get_logger("evaluation")


@dataclass
class EvalSample:
    question: str
    expected_answer: Optional[str] = None
    relevant_docs: List[str] = field(default_factory=list)


@dataclass
class EvalResult:
    sample: EvalSample
    pred_answer: str
    retrieved: List[str]
    metrics: Dict[str, float]
    error: Optional[str] = None


class EvaluationRunner:
    """Run a dataset of questions through the pipeline and score results."""

    def __init__(self, pipeline: object = None):
        self.pipeline = pipeline

    def _get_pipeline(self):
        if self.pipeline is None:
            from rag.pipeline import get_rag_pipeline
            return get_rag_pipeline()
        return self.pipeline

    def run_single(self, sample: EvalSample) -> EvalResult:
        try:
            result = self._get_pipeline().run(question=sample.question, use_memory=True)
            retrieved = [f"{c.document_name}:{c.chunk_text[:80]}" for c in result.sources]
            metrics = evaluate_answer(
                question=sample.question,
                answer=result.answer,
                context=[c.chunk_text for c in result.sources],
                expected_answer=sample.expected_answer,
            )
            if sample.relevant_docs:
                metrics.update(
                    evaluate_retrieval(sample.relevant_docs, retrieved)
                )
            return EvalResult(sample, result.answer, retrieved, metrics)
        except Exception as e:
            logger.exception(f"Sample '{sample.question}' failed: {e}")
            return EvalResult(sample, "", [], {}, error=str(e))

    def run_batch(self, samples: List[EvalSample]) -> List[EvalResult]:
        results = [self.run_single(s) for s in samples]
        return results

    def summarize(self, results: List[EvalResult]) -> Dict[str, float]:
        """Aggregate metric means across all samples."""
        if not results:
            return {}

        keys = set()
        for r in results:
            keys.update(r.metrics.keys())
        numeric_keys = [k for k in keys if k not in ("faithfulness_mode",)]

        summary: Dict[str, float] = {}
        for k in sorted(numeric_keys):
            values = [r.metrics[k] for r in results if r.metrics.get(k) is not None]
            if values:
                summary[k] = round(sum(values) / len(values), 4)
        return summary


def compute_metrics(
    question: str,
    answer: str,
    retrieved_texts: List[str],
    expected_answer: Optional[str] = None,
    expected_contexts: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Standalone metric computation for library-style use."""
    from evaluation.metrics import score_context_faithfulness

    metrics = evaluate_answer(question, answer, retrieved_texts, expected_answer)
    return metrics


def run_eval(samples: List[EvalSample], pipeline: object = None) -> dict:
    """Convenience entrypoint: run a batch and return summary + per-case data."""
    runner = EvaluationRunner(pipeline)
    results = runner.run_batch(samples)
    summary = runner.summarize(results)
    payload = {
        "samples_total": len(samples),
        "samples_failed": sum(1 for r in results if r.error),
        "summary": summary,
        "cases": [
            {
                "question": r.sample.question,
                "answer": (r.pred_answer or "")[:400],
                "retrieved": r.retrieved[:5],
                "metrics": r.metrics,
                "error": r.error,
            }
            for r in results
        ],
    }
    logger.info(
        f"Evaluation complete: {len(samples)} samples, failures={payload['samples_failed']}"
    )
    return payload