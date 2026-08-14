"""
CI gate for RAG retrieval quality.

Runs the ensemble retriever (BM25-only in CI: no embeddings/LLM required)
against the labeled evaluation dataset and asserts the retrieval metrics stay
above configurable thresholds. Fails the build (exit code != 0) when the
retriever regresses.

This is a deterministic regression guard: it verifies that the retriever can
still surface the ground-truth passages for the dataset queries. Full
answer-quality evaluation (with an LLM) can be run locally via
``python -m evaluation.run_eval``.

Usage:
    python scripts/ci_rag_eval.py [--min-recall 0.5] [--min-precision 0.25]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_corpus(samples) -> list:
    """Turn each sample's ground-truth passages into corpus Documents."""
    from langchain_core.documents import Document

    docs = []
    for idx, sample in enumerate(samples):
        for passage in sample.relevant_docs:
            docs.append(
                Document(
                    page_content=passage,
                    metadata={
                        "source": f"eval-{idx}",
                        "chunk_id": f"eval-{idx}-{len(docs)}",
                    },
                )
            )
    return docs


def main(argv=None):
    parser = argparse.ArgumentParser(description="CI gate for RAG retrieval quality")
    parser.add_argument("--dataset", default="evaluation/dataset.py")
    parser.add_argument("--min-recall", type=float, default=0.5)
    parser.add_argument("--min-precision", type=float, default=0.25)
    parser.add_argument("--json", default=False, action="store_true")
    args = parser.parse_args(argv)

    import json

    from evaluation.metrics import evaluate_retrieval
    from evaluation.run_eval import load_samples
    from rag.retriever import EnsembleRetriever

    samples = load_samples(args.dataset)
    if not samples:
        print(f"ERROR: no samples loaded from {args.dataset}", file=sys.stderr)
        return 1

    corpus_docs = build_corpus(samples)
    retriever = EnsembleRetriever(
        k_initial=10,
        k_final=3,
        use_reranker=False,
    )
    retriever.build_ensemble(vectorstore=None, corpus_docs=corpus_docs)

    per_case = []
    for sample in samples:
        retrieved = retriever.retrieve(sample.question)
        retrieved_texts = [d.page_content for d in retrieved]
        m = evaluate_retrieval(sample.relevant_docs, retrieved_texts)
        per_case.append(
            {
                "question": sample.question,
                "recall_at_k": m["recall_at_k"],
                "precision_at_k": m["precision_at_k"],
                "retrieved": retrieved_texts[:3],
            }
        )

    recall = sum(c["recall_at_k"] for c in per_case) / len(per_case)
    precision = sum(c["precision_at_k"] for c in per_case) / len(per_case)

    report = {
        "samples_total": len(per_case),
        "recall_at_k_mean": round(recall, 4),
        "precision_at_k_mean": round(precision, 4),
        "thresholds": {
            "min_recall": args.min_recall,
            "min_precision": args.min_precision,
        },
        "cases": per_case,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Samples: {report['samples_total']}")
        print(f"recall_at_k (mean):  {report['recall_at_k_mean']}  (min {args.min_recall})")
        print(f"precision_at_k (mean): {report['precision_at_k_mean']}  (min {args.min_precision})")

    ok = recall >= args.min_recall and precision >= args.min_precision
    if not ok:
        print("FAIL: retrieval quality below thresholds.", file=sys.stderr)
        return 1
    print("PASS: retrieval quality meets thresholds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())