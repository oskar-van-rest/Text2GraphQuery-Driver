import json
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from openai import OpenAI
from driver.prediction import Text2GraphSystem
from .utils import clean_query, schema_to_text, sqlite_schema_to_text

class BaseLLMSystem(Text2GraphSystem):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.base_url = config["base_url"]
        self.model = config["model"]
        self.target_lang = config.get("target_lang", "cypher")
        self.graph_name = config.get("graph_name", "default")
        self.max_workers = config.get("max_workers", 5)
        self.level_fields = config.get("level_fields", [])
        
        s_path = config["schema_path"]
        if self.target_lang == "sql" and s_path.endswith(".sqlite"):
            self.schema_text = sqlite_schema_to_text(s_path)
        else:
            try:
                with open(s_path, "r", encoding="utf-8-sig") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(s_path, "r", encoding="gbk") as f:
                    content = f.read()
            
            if s_path.endswith(".json"):
                self.schema_text = schema_to_text(json.loads(content))
            else:
                self.schema_text = content

    def _get_messages(self, question, knowledge):
        raise NotImplementedError

    def predict_batch(self, data: list) -> list:
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        def process(item):
            res = item.copy()
            for nl_f, q_f in self.level_fields:
                actual_question = ""
                actual_knowledge = ""

                # --- Strict trigger logic ---

                # 1. For level3_with_ext items: only trigger if level_3 actually exists in the data
                if nl_f == "level3_with_ext":
                    if "level_3" in item:
                        actual_question = item.get("level_3")
                        # Knowledge source: use external_knowledge for graph tasks, evidence for SQL tasks
                        actual_knowledge = item.get("external_knowledge") or item.get("evidence", "")
                
                # 2. For regular items (initial_question, level_1, level_2, level_3)
                elif nl_f in item:
                    actual_question = item.get(nl_f)
                    # For SQL tasks, always include evidence to prevent hallucination
                    if self.target_lang == "sql":
                        actual_knowledge = item.get("evidence", "")

                # 3. If trigger conditions are not met, skip directly;
                #    the corresponding _query key will not appear in res
                if not actual_question:
                    continue

                # API call logic
                for _ in range(3):
                    try:
                        resp = client.chat.completions.create(
                            model=self.model,
                            messages=self._get_messages(actual_question, actual_knowledge),
                            temperature=0.0, timeout=30
                        )
                        res[q_f] = clean_query(
                            resp.choices[0].message.content,
                            self.target_lang,
                            self.graph_name
                        )
                        break
                    except:
                        time.sleep(1)
            return res

        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(process, it) for it in data]
            for f in tqdm(as_completed(futures), total=len(futures), desc=f"Predicting {self.target_lang}"):
                results.append(f.result())
        return results