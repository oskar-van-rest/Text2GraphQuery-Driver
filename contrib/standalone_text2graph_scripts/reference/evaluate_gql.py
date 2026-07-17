"""Reference grammar, similarity, and Google BLEU evaluator.

This wrapper uses the evaluator already vendored under
``tools/eval_similarity_grammar`` in Text2GraphQuery-Driver.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import evaluate


LANG_IMPL_MAP = {
    "cypher": "tugraph-db",
    "gql": "iso-gql",
    "sql": "sqlite",
    "sql_pgq": None,
}
SUPPORTED_FENCE_LANGS = tuple(LANG_IMPL_MAP)


def extract_query_text(raw: object) -> str:
    text = "" if raw is None else str(raw)
    text = re.sub(
        r"<think>.*?</think>\s*",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()

    languages = "|".join(map(re.escape, SUPPORTED_FENCE_LANGS))
    fenced = re.search(
        rf"```(?:{languages})\s*(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not fenced:
        fenced = re.search(r"```\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)

    text = text.replace("```", "")
    return re.sub(r"\s+", " ", text).strip() or "no out"


def load_examples(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    examples = data if isinstance(data, list) else [data]
    if not examples:
        raise ValueError("Input dataset is empty")
    return examples


def infer_keys(examples: list[dict]) -> tuple[str, str]:
    prediction_candidates = (
        "generated_query",
        "predict",
        "prediction",
        "output",
        "pred",
    )
    gold_candidates = (
        "gql",
        "gold",
        "reference",
        "label",
        "initial_gql",
        "ground_truth",
        "target_query",
    )
    for example in examples:
        prediction = next(
            (key for key in prediction_candidates if str(example.get(key, "")).strip()),
            None,
        )
        gold = next(
            (key for key in gold_candidates if str(example.get(key, "")).strip()),
            None,
        )
        if prediction and gold:
            return prediction, gold
    raise ValueError(f"Cannot infer prediction/gold keys from {list(examples[0])}")


def write_query_file(
    examples: list[dict],
    key: str,
    output_path: Path,
) -> None:
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for example in examples:
            handle.write(extract_query_text(example.get(key, "")) + "\n")


def run_external_metric(
    evaluator_root: Path,
    predictions: Path,
    gold: Path,
    metric: str,
    impl: str,
) -> None:
    evaluator_script = evaluator_root / "eval" / "evaluation.py"
    if not evaluator_script.is_file():
        raise FileNotFoundError(f"Evaluator not found: {evaluator_script}")
    subprocess.run(
        [
            sys.executable,
            str(evaluator_script),
            "--input",
            str(predictions),
            "--gold",
            str(gold),
            "--etype",
            metric,
            "--impl",
            impl,
        ],
        cwd=evaluator_script.parent,
        check=True,
    )


def run_google_bleu(predictions: Path, gold: Path) -> None:
    with predictions.open("r", encoding="utf-8") as handle:
        predicted_lines = [line.strip() for line in handle]
    with gold.open("r", encoding="utf-8") as handle:
        gold_lines = [line.strip() for line in handle]
    metric = evaluate.load("google_bleu")
    result = metric.compute(predictions=predicted_lines, references=gold_lines)
    print(f"Google BLEU results:\n{result}")


def run_oracle_grammar(args: argparse.Namespace) -> None:
    """Delegate SQL/PGQ grammar validation to the Oracle-backed evaluator."""
    script = Path(__file__).with_name("ea_oracle_sql_pgq.py")
    command = [
        sys.executable,
        str(script),
        "--input-path",
        args.json_file,
        "--metrics",
        "grammar",
        "--user",
        args.oracle_user,
        "--dsn",
        args.oracle_dsn,
        "--password-env",
        args.oracle_password_env,
    ]
    if args.oracle_password_prompt:
        command.append("--password-prompt")
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repository_root = script_dir.parents[2]
    default_evaluator_root = (
        repository_root
        / "tools"
        / "eval_similarity_grammar"
        / "eval_similarity_grammar"
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--json-file", required=True)
    parser.add_argument("--language", choices=LANG_IMPL_MAP, default="gql")
    parser.add_argument("--prediction-key", default=None)
    parser.add_argument("--gold-key", default=None)
    parser.add_argument("--oracle-user", default=os.environ.get("ORACLE_USER"))
    parser.add_argument("--oracle-dsn", default=os.environ.get("ORACLE_DSN"))
    parser.add_argument("--oracle-password-env", default="ORACLE_PASSWORD")
    parser.add_argument("--oracle-password-prompt", action="store_true")
    parser.add_argument(
        "--evaluator-root",
        default=str(default_evaluator_root),
        help="Root containing eval/evaluation.py",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_path = Path(args.json_file).resolve()
    examples = load_examples(json_path)

    inferred_prediction, inferred_gold = infer_keys(examples)
    prediction_key = args.prediction_key or inferred_prediction
    gold_key = args.gold_key or inferred_gold

    predictions = json_path.with_name("predictions.txt")
    gold = json_path.with_name("gold.txt")
    write_query_file(examples, prediction_key, predictions)
    write_query_file(examples, gold_key, gold)

    print(
        f"Evaluating {len(examples)} examples as {args.language.upper()} "
        f"(prediction={prediction_key}, gold={gold_key})"
    )
    if args.language == "sql_pgq":
        if not args.oracle_user:
            raise ValueError("--oracle-user or ORACLE_USER is required for SQL/PGQ grammar")
        if not args.oracle_dsn:
            raise ValueError("--oracle-dsn or ORACLE_DSN is required for SQL/PGQ grammar")
        print("\n=== Evaluating Oracle SQL/PGQ grammar ===")
        run_oracle_grammar(args)
        metrics = ("similarity",)
    else:
        metrics = ("grammar", "similarity")

    for metric in metrics:
        print(f"\n=== Evaluating {metric} ===")
        run_external_metric(
            Path(args.evaluator_root).resolve(),
            predictions,
            gold,
            metric,
            LANG_IMPL_MAP[args.language] or "iso-gql",
        )

    print("\n=== Evaluating google-bleu ===")
    run_google_bleu(predictions, gold)


if __name__ == "__main__":
    main()
