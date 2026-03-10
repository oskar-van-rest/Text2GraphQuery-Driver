import json
import argparse
import os
import sys
from impl.db_driver.tugraph_driver import TuGraphAdapter
from impl.db_driver.spanner_driver import SpannerAdapter
from impl.db_driver.sqlite_driver import SQLiteAdapter  
from impl.text2graph_system.specialized_systems import (
    CypherZeroShotSystem, GQLZeroShotSystem, SQLZeroShotSystem,
    CypherFewShotSystem, GQLFewShotSystem, SQLFewShotSystem
)
from impl.evaluation.metrics import ExecutionAccuracy, GoogleBleu, ExternalMetric
from impl.text2graph_system.utils import clean_query

class PipelineRunner:
    def __init__(self, config_path):
        self.config_path = config_path
        self.cfg = self._load_config(config_path)
        self.db_driver = None
        self.results = []

    def _load_config(self, path):
        print(f"Loading configuration from {path}...")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_prediction_system(self):
        pred_cfg = self.cfg["prediction"]
        lang = pred_cfg.get("target_lang", "cypher").lower()
        mode = pred_cfg.get("mode", "zeroshot").lower()

        system_map = {
            ("cypher", "zeroshot"): CypherZeroShotSystem,
            ("cypher", "fewshot"): CypherFewShotSystem,
            ("gql", "zeroshot"): GQLZeroShotSystem,
            ("gql", "fewshot"): GQLFewShotSystem,
            ("sql", "zeroshot"): SQLZeroShotSystem,
            ("sql", "fewshot"): SQLFewShotSystem,
        }

        system_class = system_map.get((lang, mode))
        if not system_class:
            raise ValueError(f"Unsupported combination: lang={lang}, mode={mode}")
        
        print(f"Using System Mode: {system_class.__name__}")
        return system_class(pred_cfg)

    def _init_db_driver(self):
        eval_cfg = self.cfg["evaluation"]
        lang = self.cfg["prediction"].get("target_lang", "cypher").lower()

        try:
            if lang == "gql":
                sc = eval_cfg["spanner"]
                self.db_driver = SpannerAdapter(sc["project_id"], sc["instance_id"], sc["database_id"])
            elif lang == "sql":
                self.db_driver = SQLiteAdapter(eval_cfg["sqlite"]["db_path"])
            else:  
                tg_cfg = eval_cfg["tugraph"]  
                if not tg_cfg:
                    raise KeyError("Missing 'tugraph' configuration in 'evaluation' section.")
                self.db_driver = TuGraphAdapter(
                    tg_cfg["db_uri"],
                    tg_cfg["db_user"],
                    tg_cfg["db_pass"]
                )
                # ---------------------
            
            self.db_driver.connect()
        except Exception as e:
            print(f"Failed to connect to {lang.upper()} Database: {e}")

    def run_prediction_phase(self):
        data_path = self.cfg["data"]["input_path"]
        pred_cfg = self.cfg["prediction"]
        t_lang = pred_cfg.get("target_lang", "unknown")
        mode = pred_cfg.get("mode", "unknown")
        g_name = pred_cfg.get("graph_name", "unknown")
        
        dynamic_filename = f"{t_lang}_{mode}_{g_name}.json"
        output_dir = os.path.dirname(self.cfg["data"]["output_path"])
        output_path = os.path.join(output_dir, dynamic_filename)
        self.cfg["data"]["output_path"] = output_path

        if self.cfg["pipeline"]["run_prediction"]:
            print(f"Loading raw data from {data_path}...")
            with open(data_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            
            print("Initializing Text2Graph System...")
            system = self._get_prediction_system()
            
            print(f"Running Prediction Batch for {len(raw_data)} items...")
            self.results = system.predict_batch(raw_data)
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2, ensure_ascii=False)
            print(f"Predictions saved to {output_path}")
        else:
            print(f"Skipping prediction. Loading existing results from {output_path}...")
            if not os.path.exists(output_path):
                print(f"Error: Output file {output_path} not found.")
                sys.exit(1)
            with open(output_path, "r", encoding="utf-8") as f:
                self.results = json.load(f)

    def run_evaluation_phase(self):
        if not self.cfg["pipeline"]["run_evaluation"]:
            return

        print("\nStarting Evaluation...")
        eval_cfg = self.cfg["evaluation"]

        ea_metric = ExecutionAccuracy(self.db_driver)
        bleu_metric = GoogleBleu()
        ext_metric = ExternalMetric(eval_cfg["dbgpt_root"])
        
        levels = self.cfg["prediction"]["level_fields"]

        # Iterate over different difficulty levels in the dataset
        for _, query_key in levels:
            self._evaluate_single_level(query_key, ea_metric, bleu_metric, ext_metric)

    def _evaluate_single_level(self, query_key, ea_metric, bleu_metric, ext_metric):
        preds, golds = [], []
        lang = self.cfg["prediction"].get("target_lang", "cypher").lower()

        for item in self.results:
            if query_key in item:
                gold_val = (
                item.get("gold_query") or   
                item.get("initial_sql") or 
                item.get("initial_gql") or 
                item.get("initial_cypher") or 
                item.get("SQL") or 
                item.get("sql") or 
                item.get("gql_query") or 
                item.get("gql")
            )
                
                if gold_val:
                    # Use the dedicated clean_query logic
                    p = clean_query(item.get(query_key, ""), target_lang=lang)
                    g = clean_query(gold_val, target_lang=lang)
                    preds.append(p)
                    golds.append(g)

        if not preds:
            return

        print(f"\n{'='*40}\nEvaluating Level: {query_key} ({len(preds)} samples)\n{'='*40}")
        
        # Core logic: distinguish log files via the level_name parameter
        ea = ea_metric.compute(preds, golds)
        bleu = bleu_metric.compute(preds, golds) 
        ext_res, ext_details = ext_metric.compute(
            preds, golds,
            dataset_type=lang,
            level_name=query_key
        )
        
        print(f"\nResults for {query_key}:")
        print(f"  - EA (Acc)   : {ea:.2%}")
        print(f"  - Grammar    : {ext_res.get('Grammar', 0.0):.4f}")
        print(f"  - Similarity : {ext_res.get('Similarity', 0.0):.4f}")
        print(f"  - BLEU       : {bleu if isinstance(bleu, str) else f'{bleu:.4f}'}")

        # Pass the detailed score lists for saving
        self._save_detailed_results(query_key, preds, golds, ea, ext_details)

    def _save_detailed_results(self, query_key, preds, golds, ea, ext_details):  # Remember to pass ea in
        output_dir = os.path.join("evaluation_detail", "execution_results")
        os.makedirs(output_dir, exist_ok=True)
        detailed_records = []
        
        active_items = [item for item in self.results if query_key in item]
        
        grammar_list = ext_details.get('Grammar', [0.0] * len(preds))
        similarity_list = ext_details.get('Similarity', [0.0] * len(preds))

        for i in range(len(preds)):
            item = active_items[i]
            record = {
                "instance_id": item.get("id") or item.get("instance_id"),
                "gold_query": golds[i],
                "pred_query": item.get(query_key, ""),
                "metrics": {
                    "ea": ea,
                    "grammar": grammar_list[i],
                    "similarity": similarity_list[i]
                }
            }
            detailed_records.append(record)
            
        save_path = os.path.join(output_dir, f"{query_key}_results.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(detailed_records, f, indent=2, ensure_ascii=False)

    def cleanup(self):
        if self.db_driver:
            self.db_driver.close()

    def run(self):
        try:
            if self.cfg["pipeline"]["run_evaluation"]:
                self._init_db_driver()
            else:
                print("Evaluation is disabled. Skipping DB connection.")

            self.run_prediction_phase()
            
            if self.cfg["pipeline"]["run_evaluation"]:
                self.run_evaluation_phase()
        finally:
            self.cleanup()
            
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="experiment/test_config.json",
        help="Path to config file"
    )
    args = parser.parse_args()
    runner = PipelineRunner(args.config)
    runner.run()

if __name__ == "__main__":
    main()