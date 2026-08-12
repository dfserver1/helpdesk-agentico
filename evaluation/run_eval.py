"""
CLI entrypoint for running the evaluation harness.

Usage:
    python -m evaluation.cli --dataset evaluation/dataset.py --format json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_samples(dataset_path) -> list:
    """Load EvalSample objects from a .py module or .json file."""
    dataset_path = Path(dataset_path)
    if dataset_path.suffix == ".json":
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
        from evaluation.runner import EvalSample

        return [
            EvalSample(
                question=s["question"],
                expected_answer=s.get("expected_answer"),
                relevant_docs=s.get("relevant_docs", []),
            )
            for s in data
        ]

    import importlib.util

    spec = importlib.util.spec_from_file_location("eval_dataset", dataset_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    samples = getattr(module, "SAMPLE_DATASET", [])
    if not samples:
        raise ValueError(f"No SAMPLE_DATASET found in {dataset_path}")
    return samples


def main(argv=None):
    parser = argparse.ArgumentParser(description="HelpDesk Copilot v12 evaluation harness")
    parser.add_argument("--dataset", default="evaluation/dataset.py", help="Dataset file (.py or .json)")
    parser.add_argument("--format", default="text", choices=["text", "json"])
    parser.add_argument("--output", default=None, help="Write JSON report to file")
    args = parser.parse_args(argv)

    from evaluation.runner import run_eval

    samples = load_samples(args.dataset)
    report = run_eval(samples)

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report written to {args.output}")

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"\nSamples: {report['samples_total']} | Failures: {report['samples_failed']}")
        print("Aggregate metrics:")
        for k, v in report["summary"].items():
            print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())