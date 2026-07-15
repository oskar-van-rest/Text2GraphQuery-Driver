import argparse
import json
import logging
import math
import os
from collections import Counter
from decimal import Decimal

from google.cloud import spanner


DEFAULT_CONFIG = {
    "project_id": "",
    "instance_id": "",
    "database_id": "",
    "input_path": "",
    "output_failed_path": "",
    "output_failed_gold_path": "",
    "output_gold_valid_ids_path": "",
}

class SpannerGQLEvaluator:
    def __init__(self, project_id, instance_id, database_id):
        try:
            self.spanner_client = spanner.Client(project=project_id)
            self.instance = self.spanner_client.instance(instance_id)
            self.database = self.instance.database(database_id)
            print(f"Connected to Spanner: {project_id}/{instance_id}/{database_id}")
        except Exception as exc:
            print(f"Failed to connect to Spanner: {exc}")
            self.database = None

    def normalize(self, value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return tuple(sorted((k, self.normalize(v)) for k, v in value.items()))
        if isinstance(value, float):
            if math.isnan(value):
                return "NaN"
            return round(value, 9)
        if isinstance(value, (list, tuple)):
            return tuple(self.normalize(v) for v in value)
        if isinstance(value, (int, str, bool)) or value is None:
            return value
        return str(value)

    def compare_results(self, res_gold, res_predict, query_predict):
        def normalize_row(row):
            return tuple(self.normalize(v) for v in row)

        gold_list = [normalize_row(row) for row in res_gold]
        pred_list = [normalize_row(row) for row in res_predict]

        if "order by" in query_predict.lower():
            return gold_list == pred_list
        return Counter(gold_list) == Counter(pred_list)

    def evaluate(self, query_predict, query_gold):
        if not self.database:
            return -1, "No database connection"

        clean_gold = (query_gold or "").replace("\n", " ").strip()
        clean_predict = (query_predict or "").replace("\n", " ").strip()

        try:
            with self.database.snapshot() as snapshot:
                res_gold = list(snapshot.execute_sql(clean_gold, timeout=120.0))
        except Exception as exc:
            return -1, str(exc)

        try:
            with self.database.snapshot() as snapshot:
                res_predict = list(snapshot.execute_sql(clean_predict, timeout=120.0))
        except Exception as exc:
            return 0, str(exc)

        if self.compare_results(res_gold, res_predict, clean_predict):
            return 1, None
        return 0, "Result mismatch (Value or Order incorrect)"


def extract_fields(pair):
    if "id" in pair and "gql" in pair and "generated_query" in pair:
        return pair["id"], pair["gql"], pair["generated_query"]

    if "id" in pair and "initial_gql" in pair and "generated_query" in pair:
        return pair["id"], pair["initial_gql"], pair["generated_query"]

    if "instance_id" in pair and "gql" in pair and "generated_query" in pair:
        return pair["instance_id"], pair["gql"], pair["generated_query"]

    if "gold" in pair and "predict" in pair:
        instance_id = pair.get("instance_id") or pair.get("id") or "unknown"
        return instance_id, pair["gold"], pair["predict"]

    raise KeyError(f"Unrecognized input schema. Keys: {list(pair.keys())}")


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate generated GQL against gold GQL in Spanner.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--database-id", required=True)
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-failed-path", default=None)
    parser.add_argument("--output-failed-gold-path", default=None)
    parser.add_argument("--output-gold-valid-ids-path", default=None)
    return parser.parse_args()


def build_config(args):
    config = DEFAULT_CONFIG.copy()
    overrides = {
        "project_id": args.project_id,
        "instance_id": args.instance_id,
        "database_id": args.database_id,
        "input_path": args.input_path,
        "output_failed_path": args.output_failed_path,
        "output_failed_gold_path": args.output_failed_gold_path,
        "output_gold_valid_ids_path": args.output_gold_valid_ids_path,
    }

    for key, value in overrides.items():
        if value is not None:
            config[key] = value

    return config


def run_evaluation(config):
    input_dir = os.path.dirname(os.path.abspath(config["input_path"]))
    config["output_failed_path"] = config["output_failed_path"] or os.path.join(
        input_dir, "failed_predictions_gql.json"
    )
    config["output_failed_gold_path"] = config["output_failed_gold_path"] or os.path.join(
        input_dir, "failed_gold_gql.json"
    )

    evaluator = SpannerGQLEvaluator(
        config["project_id"],
        config["instance_id"],
        config["database_id"],
    )

    with open(config["input_path"], "r", encoding="utf-8-sig") as handle:
        pairs = json.load(handle)

    if isinstance(pairs, dict):
        pairs = [pairs]

    total = len(pairs)
    correct = 0
    failed_gold = 0

    gold_valid_ids = []
    failed_details = []
    failed_gold_details = []

    print(f"\nStarting EA Evaluation on {total} pairs...\n" + "-" * 30)

    for index, pair in enumerate(pairs, 1):
        instance_id, gold, predict = extract_fields(pair)
        score, error_msg = evaluator.evaluate(predict, gold)

        if score != -1:
            gold_valid_ids.append(instance_id)

        if score == 1:
            correct += 1
        elif score == -1:
            failed_gold += 1
            failed_gold_details.append(
                {
                    "instance_id": instance_id,
                    "gold": gold,
                    "predict": predict,
                    "error": error_msg,
                }
            )
        else:
            failed_details.append(
                {
                    "instance_id": instance_id,
                    "gold": gold,
                    "predict": predict,
                    "error": error_msg,
                }
            )

        print(f"[{index}/{total}] ID: {instance_id} | Score: {score}")

    effective_total = total - failed_gold
    accuracy = correct / effective_total if effective_total > 0 else 0

    gold_valid_ids_path = config["output_gold_valid_ids_path"].strip()
    if gold_valid_ids_path:
        with open(gold_valid_ids_path, "w", encoding="utf-8") as handle:
            json.dump(gold_valid_ids, handle, indent=4, ensure_ascii=False)

    with open(config["output_failed_path"], "w", encoding="utf-8") as handle:
        json.dump(failed_details, handle, indent=4, ensure_ascii=False)

    with open(config["output_failed_gold_path"], "w", encoding="utf-8") as handle:
        json.dump(failed_gold_details, handle, indent=4, ensure_ascii=False)

    print("-" * 30)
    print(f"Total pairs: {total}")
    if gold_valid_ids_path:
        print(f"Gold GQL Valid: {len(gold_valid_ids)} (Saved to {gold_valid_ids_path})")
    else:
        print("Gold GQL Valid: {0} (Not saved: output_gold_valid_ids_path is empty)".format(len(gold_valid_ids)))
    print(f"Gold GQL Failed: {failed_gold} (Saved to {config['output_failed_gold_path']}): {len(failed_gold_details)}")
    print(f"Correct Predictions: {correct}")
    print(f"Failed Predictions (Saved to {config['output_failed_path']}): {len(failed_details)}")
    print(f"\nExecution Accuracy (EA): {accuracy:.2%}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    run_evaluation(build_config(parse_args()))
