"""Oracle SQL/PGQ grammar and execution-accuracy evaluator.

The evaluator obtains connection data only at runtime. It never writes a
password to its input or report files. Gold queries are executed first; a gold
query that fails is excluded from the execution-accuracy denominator.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import oracledb
except ImportError as exc:  # pragma: no cover - exercised at runtime
    raise SystemExit(
        "Missing dependency: install python-oracledb with "
        "`python -m pip install oracledb`."
    ) from exc


DEFAULT_DSN = None
IGNORED_GRAMMAR_ERROR_CODES = (
    "ORA-40983",
    "ORA-40954",
    "ORA-00904",
    "ORA-40996",
    "ORA-49044",
    "ORA-00942",
    "ORA-40981",
    "ORA-40990",
    "ORA-49011",
)


def is_ignored_grammar_error(error: Exception) -> bool:
    """Return whether Oracle failed only object-resolution or semantic checks."""
    message = str(error)
    return any(code in message for code in IGNORED_GRAMMAR_ERROR_CODES)


def enable_thick_mode(lib_dir: str | None) -> None:
    """Enable the optional Oracle Thick client mode."""
    if not lib_dir:
        raise RuntimeError(
            "Oracle Thick mode needs an Oracle client library directory. "
            "Pass --oracle-client-lib-dir or set ORACLE_HOME."
        )
    oracledb.init_oracle_client(lib_dir=lib_dir)


def connect(args: argparse.Namespace, password: str):
    """Connect in the selected mode, with optional Thick-mode fallback."""
    if args.thick_mode == "on":
        enable_thick_mode(args.oracle_client_lib_dir)
        return oracledb.connect(user=args.user, password=password, dsn=args.dsn)

    try:
        return oracledb.connect(user=args.user, password=password, dsn=args.dsn)
    except oracledb.DatabaseError as exc:
        if args.thick_mode != "auto" or "DPY-4021" not in str(exc):
            raise
        enable_thick_mode(args.oracle_client_lib_dir)
        return oracledb.connect(user=args.user, password=password, dsn=args.dsn)


def strip_terminal_semicolon(query: str) -> str:
    """Return one Oracle statement suitable for the Python DB API."""
    text = (query or "").strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    if not text or ";" in text:
        raise ValueError("Expected exactly one SQL statement")
    return text


def read_only_query(query: str) -> str:
    """Restrict execution accuracy to read-only statements."""
    text = strip_terminal_semicolon(query)
    without_comments = re.sub(r"(?s)/\*.*?\*/", "", text).lstrip()
    without_comments = re.sub(r"(?m)^\s*--.*$", "", without_comments).lstrip()
    if not re.match(r"(?i)^(?:select|with)\b", without_comments):
        raise ValueError("Execution accuracy accepts only SELECT or WITH queries")
    return text


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, float):
        return "NaN" if math.isnan(value) else round(value, 9)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return tuple(normalize(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, normalize(item)) for key, item in value.items()))
    if hasattr(value, "read"):
        return normalize(value.read())
    return str(value)


def results_match(gold_rows: list[tuple], predicted_rows: list[tuple], predicted_query: str) -> bool:
    gold = [tuple(normalize(value) for value in row) for row in gold_rows]
    predicted = [tuple(normalize(value) for value in row) for row in predicted_rows]
    if re.search(r"(?i)\border\s+by\b", predicted_query):
        return gold == predicted
    return Counter(gold) == Counter(predicted)


def parse_only(cursor: Any, query: str) -> None:
    """Ask Oracle to parse the statement without executing it."""
    statement = strip_terminal_semicolon(query)
    cursor.execute(
        """
        DECLARE
          c INTEGER;
        BEGIN
          c := DBMS_SQL.OPEN_CURSOR;
          BEGIN
            DBMS_SQL.PARSE(c, :query_text, DBMS_SQL.NATIVE);
          EXCEPTION
            WHEN OTHERS THEN
              IF DBMS_SQL.IS_OPEN(c) THEN DBMS_SQL.CLOSE_CURSOR(c); END IF;
              RAISE;
          END;
          DBMS_SQL.CLOSE_CURSOR(c);
        END;
        """,
        query_text=statement,
    )


def load_pairs(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as handle:
        data = json.load(handle)
    pairs = data if isinstance(data, list) else [data]
    if not pairs:
        raise ValueError("Input dataset is empty")
    return pairs


def infer_field(pair: dict[str, Any], candidates: tuple[str, ...], name: str) -> str:
    for field in candidates:
        if str(pair.get(field, "")).strip():
            return field
    raise ValueError(f"Could not infer {name} field from {list(pair)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Oracle SQL/PGQ predictions with Oracle parsing and execution."
    )
    parser.add_argument("--input-path", required=True, help="Prediction JSON array or object")
    parser.add_argument("--user", default=os.environ.get("ORACLE_USER"))
    parser.add_argument("--dsn", default=os.environ.get("ORACLE_DSN", DEFAULT_DSN))
    parser.add_argument("--password-env", default="ORACLE_PASSWORD")
    parser.add_argument("--password-prompt", action="store_true")
    parser.add_argument(
        "--thick-mode", choices=("auto", "on", "off"), default="auto",
        help="Use the Oracle client for non-TCP aliases; auto retries after DPY-4021.",
    )
    parser.add_argument(
        "--oracle-client-lib-dir",
        default=(os.path.join(os.environ["ORACLE_HOME"], "lib") if os.environ.get("ORACLE_HOME") else None),
        help="Oracle client library directory for Thick mode (defaults to $ORACLE_HOME/lib).",
    )
    parser.add_argument("--prediction-field", default=None)
    parser.add_argument("--gold-field", default=None)
    parser.add_argument("--id-field", default=None)
    parser.add_argument(
        "--metrics", nargs="+", choices=("grammar", "execution"),
        default=("grammar", "execution"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--output-path", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.user:
        raise SystemExit("Missing Oracle user: pass --user or set ORACLE_USER")
    if not args.dsn:
        raise SystemExit("Missing Oracle DSN: pass --dsn or set ORACLE_DSN")
    password = os.environ.get(args.password_env)
    if not password and args.password_prompt:
        password = getpass.getpass(f"Oracle password for {args.user}: ")
    if not password:
        raise SystemExit(
            f"Missing password: set {args.password_env} or pass --password-prompt"
        )

    input_path = Path(args.input_path).resolve()
    pairs = load_pairs(input_path)
    prediction_field = args.prediction_field or infer_field(
        pairs[0], ("generated_query", "predict", "prediction", "output", "pred"), "prediction"
    )
    gold_field = args.gold_field or infer_field(
        pairs[0], ("initial_sql_pgq", "initial_gql", "gql", "gold", "reference", "label"), "gold"
    )
    id_field = args.id_field or next(
        (field for field in ("instance_id", "id") if field in pairs[0]), None
    )

    connection = connect(args, password)
    connection.call_timeout = int(args.timeout_seconds * 1000)
    details: list[dict[str, Any]] = []
    grammar_correct = 0
    gold_execution_valid = 0
    execution_correct = 0
    try:
        with connection.cursor() as cursor:
            for position, pair in enumerate(pairs, 1):
                prediction = str(pair.get(prediction_field) or "")
                gold = str(pair.get(gold_field) or "")
                detail: dict[str, Any] = {
                    "index": position,
                    "instance_id": pair.get(id_field) if id_field else position,
                }

                if "grammar" in args.metrics:
                    try:
                        parse_only(cursor, prediction)
                        detail["grammar"] = 1
                        grammar_correct += 1
                    except Exception as exc:
                        if is_ignored_grammar_error(exc):
                            # DBMS_SQL.PARSE resolves property-graph labels and
                            # properties in addition to checking SQL syntax.
                            # Treat these unresolved-name errors as semantic,
                            # not grammatical, failures.
                            detail["grammar"] = 1
                            detail["grammar_ignored_semantic_error"] = str(exc)
                            grammar_correct += 1
                        else:
                            detail["grammar"] = 0
                            detail["grammar_error"] = str(exc)

                if "execution" in args.metrics:
                    try:
                        cursor.execute(read_only_query(gold))
                        gold_rows = cursor.fetchall()
                        detail["gold_execution_valid"] = True
                        gold_execution_valid += 1
                    except Exception as exc:
                        detail["gold_execution_valid"] = False
                        detail["gold_execution_error"] = str(exc)
                    else:
                        try:
                            normalized_prediction = read_only_query(prediction)
                            cursor.execute(normalized_prediction)
                            predicted_rows = cursor.fetchall()
                            detail["execution"] = int(
                                results_match(gold_rows, predicted_rows, normalized_prediction)
                            )
                            execution_correct += detail["execution"]
                        except Exception as exc:
                            detail["execution"] = 0
                            detail["execution_error"] = str(exc)
                details.append(detail)
    finally:
        connection.close()

    summary: dict[str, Any] = {
        "input_path": str(input_path),
        "oracle_user": args.user,
        "oracle_dsn": args.dsn,
        "prediction_field": prediction_field,
        "gold_field": gold_field,
        "total_pairs": len(pairs),
    }
    if "grammar" in args.metrics:
        summary["grammar_correct"] = grammar_correct
        summary["grammar_accuracy"] = grammar_correct / len(pairs)
    if "execution" in args.metrics:
        summary["gold_execution_valid"] = gold_execution_valid
        summary["execution_correct"] = execution_correct
        summary["execution_accuracy"] = (
            execution_correct / gold_execution_valid if gold_execution_valid else 0.0
        )

    output_path = Path(args.output_path).resolve() if args.output_path else input_path.with_name(
        f"{input_path.stem}_oracle_sql_pgq_evaluation.json"
    )
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "details": details}, handle, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2))
    print(f"Detailed report: {output_path}")


if __name__ == "__main__":
    main()
