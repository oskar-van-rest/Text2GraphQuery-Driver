import argparse
import os
import time
import subprocess
import logging
import json
import traceback
import multiprocessing as mp
from neo4j import GraphDatabase


class ExecutionEvaluator:
    def __init__(
        self,
        uri="bolt://localhost:7687",
        user="admin",
        password="",
        docker_container="tugraph_demo",
        auto_restart=True,
        timeout_sec=60.0,
        recover_cooldown_sec=30.0,
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.docker_container = docker_container
        self.auto_restart = auto_restart

        self.timeout_sec = float(timeout_sec)
        self.recover_cooldown_sec = float(recover_cooldown_sec)
        self._last_recover_ts = 0.0

        # 鐢ㄤ簬鈥滆繛閫氭€ф帰娴?澶嶇敤 recover 閫昏緫鈥?        self.driver = None
        self._connect()

    # ------------------ connectivity ------------------
    def _connect_once(self):
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
            self.driver = None

        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            connection_timeout=10,
        )
        self.driver.verify_connectivity()
        print(f"Connected to TuGraph (Bolt) at {self.uri}")

    def _connect(self, tries=3, interval=1):
        last_err = None
        for _ in range(tries):
            try:
                self._connect_once()
                return True
            except Exception as e:
                last_err = e
                time.sleep(interval)
        print(f"[ConnectFail] {last_err}")
        self.driver = None
        return False

    # ------------------ docker / recover ------------------
    def _start_lgraph_server(self):
        cmd = [
            "docker",
            "exec",
            self.docker_container,
            "bash",
            "-lc",
            "lgraph_server -c /usr/local/etc/lgraph.json -d start",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            print(
                f"[AutoRecover] lgraph_server start rc={p.returncode}, stderr={p.stderr.strip()}"
            )
        else:
            out = (p.stdout or "").strip()
            if out:
                print(f"[AutoRecover] lgraph_server: {out}")

    def _docker_restart_tugraph(self):
        if not self.auto_restart:
            return
        print(f"[AutoRecover] Restarting TuGraph container: {self.docker_container}")
        p = subprocess.run(
            ["docker", "restart", self.docker_container],
            check=False,
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            raise RuntimeError(
                f"docker restart failed: rc={p.returncode}, stderr={p.stderr.strip()}"
            )

    def _recover(self):
        # 鍐峰嵈锛氶伩鍏嶆姈鍔ㄦ椂鐤媯閲嶅惎
        now = time.time()
        if now - self._last_recover_ts < self.recover_cooldown_sec:
            time.sleep(self.recover_cooldown_sec - (now - self._last_recover_ts))
        self._last_recover_ts = time.time()

        self._docker_restart_tugraph()
        time.sleep(2)
        self._start_lgraph_server()

        deadline = time.time() + 360

        while time.time() < deadline:
            if self._connect(tries=1, interval=0):
                return
            time.sleep(2)

        raise RuntimeError("TuGraph did not recover within 360s")

    # ------------------ query execution (process timeout) ------------------
    @staticmethod
    def _query_worker(uri, user, password, db_name, query, out_q):
        """
        瀛愯繘绋嬮噷鎵ц鍗曟潯鏌ヨ锛氭柊寤?driver -> run -> 杩斿洖缁撴灉
        """
        try:
            driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                connection_timeout=10,
            )
            driver.verify_connectivity()
            with driver.session(database=db_name) as session:
                data = session.run(query).data()
            driver.close()
            out_q.put(("ok", data))
        except Exception as e:
            out_q.put(("err", str(e) + "\n" + traceback.format_exc()))

    def _run_query_process(self, query, db_name):
        """
        鐖惰繘绋嬶細鍚姩瀛愯繘绋嬭窇 query锛涜秴鏃跺氨 terminate锛屼繚璇佷笉浼氬爢骞界伒鏌ヨ
        """
        ctx = mp.get_context("spawn")
        out_q = ctx.Queue()
        p = ctx.Process(
            target=ExecutionEvaluator._query_worker,
            args=(self.uri, self.user, self.password, db_name, query, out_q),
            daemon=True,
        )
        p.start()
        p.join(self.timeout_sec)

        if p.is_alive():
            p.terminate()
            p.join(5)
            raise TimeoutError(f"Query execution exceeded {self.timeout_sec} seconds")

        if out_q.empty():
            raise RuntimeError("Worker exited without returning result")

        status, payload = out_q.get()
        if status == "ok":
            return payload
        raise RuntimeError(payload)

    def _is_connection_like_error(self, e: Exception) -> bool:
        """
        鍙鐪熸鐨勮繛鎺?鎻℃墜/IO 閿欒瑙﹀彂 recover銆?        鏁版嵁搴撳唴閮ㄩ敊璇紙bad any_cast / internal error 绛夛級涓嶉噸鍚紝鍙澶辫触銆?        """
        msg = str(e).lower()

        # Database semantic/query errors should not trigger container recovery.
        if any(k in msg for k in [
            "cypherexception",
            "internal error",
            "bad any_cast",
            "syntaxerror",
            "typeerror",
            "semantic",
            "invalid",
            "constraint",
        ]):
            return False

        # Only connection, IO, and handshake failures are recoverable here.
        return any(k in msg for k in [
            "failed to read four byte bolt handshake",
            "connection refused",
            "service unavailable",
            "failed to establish",
            "broken pipe",
            "connection reset",
            "connection was closed",
            "timed out",
            "timeout",
            "session expired",
            "failed to read",
            "failed to write",
            "network is unreachable",
        ])

    # ------------------ compare / evaluate ------------------
    def close(self):
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
            self.driver = None

    def compare_results(self, res_gold, res_predict):
        def normalize(value):
            if isinstance(value, float):
                return round(value, 9)
            if isinstance(value, (int, str, bool)) or value is None:
                return value
            if hasattr(value, "isoformat"):
                return value.isoformat()
            if isinstance(value, (list, tuple)):
                return tuple(normalize(v) for v in value)
            if isinstance(value, dict):
                return tuple(sorted((k, normalize(v)) for k, v in value.items()))
            return str(value)

        def normalize_row(row):
            return tuple(normalize(v) for v in row.values())

        return {normalize_row(r) for r in res_gold} == {normalize_row(r) for r in res_predict}

    def evaluate(self, query_predict, query_gold, database):
        if not self.driver:
            ok = self._connect(tries=2, interval=1)
            if not ok:
                self._recover()

        def run_with_limit(query, db_name):
            try:
                return self._run_query_process(query, db_name)
            except Exception as e:
                # 闈炶繛鎺ョ被閿欒锛氱洿鎺ユ姏鍑猴紝璁╀笂灞傝澶辫触
                if not self._is_connection_like_error(e):
                    raise
                print(f"[AutoRecover] Detected connection issue: {e}")
                self._recover()
                return self._run_query_process(query, db_name)

        # Gold
        try:
            res_gold = run_with_limit(query_gold, database)
        except Exception as e:
            return -1, f"Gold query execution error or timeout: {str(e)}"

        # Predict
        try:
            res_predict = run_with_limit(query_predict, database)
        except Exception as e:
            return 0, f"Predict query execution error or timeout: {str(e)}"

        return (1, None) if self.compare_results(res_gold, res_predict) else (0, "Result mismatch")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Reference execution-accuracy evaluator for Cypher/TuGraph."
    )
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--database", required=True, help="TuGraph database name")
    parser.add_argument("--uri", default=os.environ.get("TUGRAPH_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.environ.get("TUGRAPH_USER", "admin"))
    parser.add_argument("--password", default=os.environ.get("TUGRAPH_PASSWORD"))
    parser.add_argument("--docker-container", default=os.environ.get("TUGRAPH_CONTAINER", "tugraph_demo"))
    parser.add_argument("--output-failed-path", default=None)
    parser.add_argument("--output-gold-valid-ids-path", default=None)
    parser.add_argument("--valid-ids-path", default=None)
    parser.add_argument("--id-field", default="id")
    parser.add_argument("--gold-field", default="initial_gql")
    parser.add_argument("--prediction-field", default="generated_query")
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument("--no-auto-restart", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.password:
        raise ValueError("Missing TuGraph password: set TUGRAPH_PASSWORD")

    input_path = os.path.abspath(args.input_path)
    input_dir = os.path.dirname(input_path)
    output_failed_path = args.output_failed_path or os.path.join(input_dir, "failed_predictions_cypher.json")
    output_gold_valid_ids_path = (
        args.output_gold_valid_ids_path
        or os.path.join(input_dir, "gold_executable_ids.json")
    )

    valid_ids = None
    if args.valid_ids_path:
        with open(args.valid_ids_path, "r", encoding="utf-8") as handle:
            valid_ids = set(json.load(handle))

    with open(input_path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    items = data if isinstance(data, list) else [data]
    if valid_ids is not None:
        items = [item for item in items if item.get(args.id_field) in valid_ids]

    evaluator = ExecutionEvaluator(
        uri=args.uri,
        user=args.user,
        password=args.password,
        docker_container=args.docker_container,
        auto_restart=not args.no_auto_restart,
        timeout_sec=args.timeout_sec,
    )

    correct = 0
    evaluated_count = 0
    gold_error_count = 0
    failed_details = []
    gold_executable_ids = []

    try:
        for index, item in enumerate(items, 1):
            instance_id = item.get(args.id_field, f"row-{index}")
            gold_query = item.get(args.gold_field, "")
            pred_query = item.get(args.prediction_field, "")
            score, error_msg = evaluator.evaluate(
                pred_query,
                gold_query,
                database=args.database,
            )

            if score != -1:
                gold_executable_ids.append(instance_id)
                evaluated_count += 1
            if score == 1:
                correct += 1
            elif score == -1:
                gold_error_count += 1
            else:
                failed_details.append(
                    {
                        "id": instance_id,
                        "gold_query": gold_query,
                        "predict_query": pred_query,
                        "error_info": error_msg,
                    }
                )
            print(f"[{index}/{len(items)}] ID: {instance_id} | Score: {score}")
    finally:
        evaluator.close()

    with open(output_failed_path, "w", encoding="utf-8") as handle:
        json.dump(failed_details, handle, indent=2, ensure_ascii=False)
    with open(output_gold_valid_ids_path, "w", encoding="utf-8") as handle:
        json.dump(gold_executable_ids, handle, indent=2, ensure_ascii=False)

    accuracy = correct / evaluated_count if evaluated_count else 0.0
    print("-" * 30)
    print(f"Total pairs: {len(items)}")
    print(f"Gold Cypher Valid: {len(gold_executable_ids)}")
    print(f"Gold Cypher Failed: {gold_error_count}")
    print(f"Correct Predictions: {correct}")
    print(f"Execution Accuracy (EA): {accuracy:.2%}")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    logging.basicConfig(level=logging.CRITICAL)
    main()
