import os
import sys
import shutil
import subprocess
import json
import re
import math
import evaluate
from collections import Counter
from decimal import Decimal
from driver.evaluation import BaseMetric, DatabaseDriver

class ExecutionAccuracy(BaseMetric):
    def __init__(self, driver: DatabaseDriver):
        self.driver = driver

    def _normalize(self, value):
        """Recursive normalization of data: supports Spanner, SQLite, and TuGraph."""
        if value is None: return None
        if isinstance(value, (bytes, bytearray)): return value.hex()
        if isinstance(value, Decimal): return float(value)
        if isinstance(value, float):
            if math.isnan(value): return "NaN"
            return round(value, 9)
        if isinstance(value, (int, str, bool)): return value
        if isinstance(value, (list, tuple)):
            return tuple(self._normalize(v) for v in value)
        if isinstance(value, dict):
            return tuple(sorted((k, self._normalize(v)) for k, v in value.items()))
        return str(value)

    def _compare_results(self, res_gold, res_predict, query_predict):
        """Compare query result sets (multiset comparison)"""
        def normalize_rows(res):
            if not res: return []
            return [tuple(self._normalize(v) for v in (r.values() if isinstance(r, dict) else r)) for r in res]

        gold_list = normalize_rows(res_gold)
        pred_list = normalize_rows(res_predict)
        is_ordered = "order by" in (query_predict or "").lower()
        if is_ordered:
            return gold_list == pred_list
        return Counter(gold_list) == Counter(pred_list)

    def compute(self, predictions: list, golds: list, **kwargs) -> float:
        db_id = kwargs.get("db_id", "default")
        correct, total = 0, 0
        for pred, gold in zip(predictions, golds):
            if not pred or not gold:
                total += 1
                continue
            res_gold = self.driver.query(gold, db_name=db_id)
            if res_gold is None:
                total += 1
                continue
            res_pred = self.driver.query(pred, db_name=db_id)
            if res_pred is not None and self._compare_results(res_gold, res_pred, pred):
                correct += 1
            total += 1
        return correct / total if total > 0 else 0.0

class GoogleBleu(BaseMetric):
    def compute(self, predictions: list, golds: list, **kwargs):
        try:
            bleu = evaluate.load('google_bleu')
            safe_preds = [p.replace('\n', ' ').strip() if p else "" for p in predictions]
            safe_golds = [g.replace('\n', ' ').strip() if g else "" for g in golds]
            res = bleu.compute(predictions=safe_preds, references=[[g] for g in safe_golds])
            return res['google_bleu']
        except Exception as e:
            print(f"Warning: BLEU failed: {e}")
            return 0.0

class ExternalMetric(BaseMetric):
    def __init__(self, dbgpt_root: str):
        self.dbgpt_root = dbgpt_root
        self.temp_dir = os.path.abspath("temp_eval_results_oop")

    def _clean_query_text(self, query):
        """Clean predictions and gold labels by removing the GRAPH/USE prefixes"""
        if not query: return ""
        cleaned = re.sub(r'(?i)^(GRAPH|USE)\s+[\w\-]+\s+', '', query)
        return cleaned.strip()

    def _parse_log_score(self, log_content, etype):
        """Parse log contents and return the average score"""
        try:
            log_content = log_content.strip()
            if not log_content: return 0.0
            
            if log_content.startswith('['):
                data = json.loads(log_content)
                if isinstance(data, list) and len(data) > 0:
                    scores = [float(item.get('score', 0)) for item in data if 'score' in item]
                    return sum(scores) / len(scores) if scores else 0.0
            
            match = re.search(r'(?:accuracy|score)[:\s"]+([0-9.]+)', log_content, re.IGNORECASE)
            if match: return float(match.group(1))
        except: pass
        return 0.0

    def compute(self, predictions: list, golds: list, **kwargs) -> tuple:
        """
        return (results_dict, detailed_scores_dict)
        results: {'Grammar': 0.54, 'Similarity': 0.71}
        detailed_scores: {'Grammar': [1.0, 0.0, ...], 'Similarity': [0.85, 0.92, ...]}
        """
        lang = kwargs.get('dataset_type', 'cypher').lower()
        level_name = str(kwargs.get('level_name', 'unknown')).replace(' ', '_')
        
        if not os.path.exists(self.dbgpt_root):
            print(f"CRITICAL: dbgpt_root not found: {self.dbgpt_root}")
            return {'Grammar': 0.0, 'Similarity': 0.0}, {}

        impl = 'iso-gql' if 'gql' in lang else 'tugraph-db'

        # Clean data and prepare temporary files
        os.makedirs(self.temp_dir, exist_ok=True)
        pred_file = os.path.join(self.temp_dir, 'predictions.txt')
        gold_file = os.path.join(self.temp_dir, 'gold.txt')
        
        clean_preds = [self._clean_query_text(p).replace('\n', ' ') for p in predictions]
        clean_golds = [self._clean_query_text(g).replace('\n', ' ') for g in golds]

        with open(pred_file, 'w', encoding='utf-8') as f: f.write('\n'.join(clean_preds))
        with open(gold_file, 'w', encoding='utf-8') as f: f.write('\n'.join(clean_golds))

        results = {}
        detailed_scores = {}
        original_cwd = os.getcwd()
        
        try:
            os.chdir(self.dbgpt_root) 
            
            possible_rel_paths = [
                os.path.join('eval_similarity_grammar', 'eval', 'evaluation.py'),
                os.path.join('eval_similarity_grammar', 'eval_similarity_grammar', 'eval', 'evaluation.py')
            ]
            script_path = next((p for p in possible_rel_paths if os.path.exists(p)), None)

            if not script_path:
                print(f"CRITICAL: evaluation.py not found in {os.getcwd()}")
                return {'Grammar': 0.0, 'Similarity': 0.0}, {}

            for etype in ['grammar', 'similarity']:
                cmd = [
                    sys.executable, script_path, 
                    '--input', pred_file, 
                    '--gold', gold_file, 
                    '--etype', etype, 
                    '--impl', impl,
                    '--level', level_name
                ]
                
                process = subprocess.run(cmd, capture_output=True, text=True)
                if process.returncode != 0:
                    print(f"Eval Script Crashed ({level_name}-{etype}): {process.stderr}")
                    results[etype.capitalize()] = 0.0
                    detailed_scores[etype.capitalize()] = [0.0] * len(predictions)
                    continue

                # Read the logs
                script_abs_path = os.path.abspath(script_path)
                base_dir = os.path.dirname(os.path.dirname(script_abs_path)) 
                log_path = os.path.join(base_dir, 'output', 'logs', f'eval_{etype}_{level_name}.log')
                
                if not os.path.exists(log_path):
                    log_path = os.path.join(base_dir, 'output', 'logs', f'eval_{etype}.log')

                if os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8') as f:
                        log_content = f.read()
                        # 1. Aggregate and compute the average score
                        results[etype.capitalize()] = self._parse_log_score(log_content, etype)
                        
                        # 2. Extract the raw score for each individual record
                        try:
                            log_data = json.loads(log_content)
                            detailed_scores[etype.capitalize()] = [float(item.get('score', 0)) for item in log_data]
                        except Exception:
                            detailed_scores[etype.capitalize()] = [0.0] * len(predictions)
                else:
                    results[etype.capitalize()] = 0.0
                    detailed_scores[etype.capitalize()] = [0.0] * len(predictions)
                    
        finally:
            os.chdir(original_cwd)
        
        return results, detailed_scores