from __future__ import annotations  # allow "str | None" annotations on Python 3.9
import json
import time
import argparse
import os
import random
import re
from openai import OpenAI
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3

# Default OpenAI-compatible endpoint for Qwen. Override with --base_url or LLM_BASE_URL.
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def sqlite_schema_to_text(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    lines = []
    for t in tables:
        cur.execute(f"PRAGMA table_info('{t}')")
        cols = cur.fetchall()
        col_str = ", ".join([f"{c[1]} {c[2]}" for c in cols])
        lines.append(f"- {t}({col_str})")
    conn.close()
    return "Tables:\n" + "\n".join(lines)


# === 1) Schema -> text ===
def schema_to_text(schema_json):
    lines, vertices, edges = [], [], []
    for item in schema_json.get("schema", []):
        label = item.get("label")
        type_ = item.get("type")
        props = item.get("properties", []) or []
        props_str = ", ".join(
            [f'{p["name"]}: {p["type"]}' + (" (optional)" if p.get("optional") else "")
             for p in props]
        )

        if type_ == "VERTEX":
            primary = item.get("primary")
            if primary:
                vertices.append(f"- {label} [primary: {primary}] ({props_str})")
            else:
                vertices.append(f"- {label}({props_str})")

        elif type_ == "EDGE":
            temporal = item.get("temporal")
            if temporal:
                edges.append(f"- {label} [temporal: {temporal}] ({props_str})")
            else:
                edges.append(f"- {label}({props_str})")

    if vertices:
        lines.append("Vertex types:")
        lines.extend(vertices)
    if edges:
        lines.append("\nEdge types:")
        lines.extend(edges)
    return "\n".join(lines)

# === 2) Prompt builder (Cypher / Spanner Graph GQL) ===
def build_prompt(
    nl_question: str,
    specific_knowledge: str,
    schema_text: str,
    target_lang: str,
    graph_name: str | None,
    prompt_style: str = "fewshot",
):
    if not specific_knowledge:
        specific_knowledge = "No specific external knowledge provided."

    reverse_alias_instruction = ""
    # Enable this block again when evaluating alias-focused datasets.
    # reverse_alias_instruction = (
    #     "Before writing the query, internally normalize the user's wording to the schema:\n"
    #     "1. Identify nouns, verbs, and phrases in the question that may be aliases or paraphrases of schema labels, relationships, or properties.\n"
    #     "2. Match uncertain terms to the closest canonical schema element using only the provided schema and domain knowledge.\n"
    #     "3. Pay special attention to relationship direction and distinguish node types from relationships and property values.\n"
    #     "4. Preserve literal filter values from the question exactly; do not replace values with property names.\n"
    #     "5. Do not output this normalization process. Output only the final query string.\n"

    # )

    cypher_system = (
        "You are an expert in graph query languages, specifically openCypher.\n"
        "Schema:\n"
        f"{schema_text}\n\n"
        "Domain knowledge:\n"
        f"{specific_knowledge}\n\n"
        f"{reverse_alias_instruction}"
        "Task: Convert the user's natural language question into a openCypher query.\n"
        "Output: Return only the query string."
    )

    gql_system = (
        "You are an expert in graph query languages, specifically ISO GQL (ISO/IEC 39075).\n"
        "Schema (DDL):\n"
        f"{schema_text}\n\n"
        "Domain knowledge:\n"
        f"{specific_knowledge}\n\n"
        f"{reverse_alias_instruction}"
        "Task: Convert the user's natural language question into a ISO GQL query.\n"
        "Output: Return only the query string."
    )

    sql_system = (
        "You are an expert in relational query languages, specifically SQL.\n"
        "Schema:\n"
        f"{schema_text}\n\n"
        "Domain knowledge:\n"
        f"{specific_knowledge}\n\n"
        f"{reverse_alias_instruction}"
        "Task: Convert the user's natural language question into a SQL query.\n"
        "Output: Return only the query string.\n"
    )

    if prompt_style == "fewshot":
        cypher_system = (
            "You are an expert in graph query languages, specifically openCypher.\n"
            "The database schema is as follows:\n"
            f"{schema_text}\n\n"
            "Domain Knowledge:\n"
            f"{specific_knowledge}\n\n"
            "Task: Convert the user's natural language question into a openCypher query.\n"
            "Output: Return only the query string.\n\n"
            "The user's question and corresponding output examples are as follows:\n\n"
            "Example 1\n"
            "Question: Which characters have a path to \"Catelyn-Stark\" in the interaction network with a maximum of 3 hops?\n"
            "Output: MATCH (c:Character)-[:INTERACTS*1..3]->(target:Character {name: 'Catelyn-Stark'}) RETURN DISTINCT c.name\n\n"
            "Example 2\n"
            "Question: How many people have directed more than two movies?\n"
            "Output: MATCH (p:Person)-[:DIRECTED]->(m:Movie) WITH p, count(m) AS moviesDirected WHERE moviesDirected > 2 RETURN count(p) AS directorsCount\n\n"
            "Example 3\n"
            "Question: List the top 5 movies with the most production companies involved.\n"
            "Output: MATCH (m:Movie)-[:PRODUCED_BY]->(pc:ProductionCompany) WITH m, COUNT(pc) AS productionCompanyCount ORDER BY productionCompanyCount DESC LIMIT 5 RETURN m.title AS MovieTitle, productionCompanyCount\n"
        )

        gql_system = (
            "You are an expert in graph query languages, specifically ISO GQL (ISO/IEC 39075).\n"
            "The database schema is as follows:\n"
            f"{schema_text}\n\n"
            "Domain Knowledge:\n"
            f"{specific_knowledge}\n\n"
            "Task: Convert the user's natural language question into a ISO GQL query.\n"
            "Output: Return only the query string.\n\n"
            "The user's question and corresponding output examples are as follows:\n\n"
            "Example 1\n"
            "Question: Which characters have a path to \"Catelyn-Stark\" in the interaction network with a maximum of 3 hops?\n"
            "Output: MATCH (c:Character)-[:INTERACTS]->{1,3}(target:Character {name: 'Catelyn-Stark'}) RETURN DISTINCT c.name\n\n"
            "Example 2\n"
            "Question: How many people have directed more than two movies?\n"
            "Output: MATCH (p:Person)-[:DIRECTED]->(m:Movie) RETURN p, count(m) AS moviesDirected NEXT FILTER moviesDirected > 2 RETURN count(p) AS directorsCount\n\n"
            "Example 3\n"
            "Question: List the top 5 movies with the most production companies involved.\n"
            "Output: MATCH (m:Movie)-[:PRODUCED_BY]->(pc:ProductionCompany) RETURN m, COUNT(pc) AS productionCompanyCount ORDER BY productionCompanyCount DESC LIMIT 5 NEXT RETURN m.title AS MovieTitle, productionCompanyCount\n"
        )

        sql_system = (
            "You are an expert in relational query languages, specifically SQL.\n"
            "The database schema is as follows:\n"
            f"{schema_text}\n\n"
            "Domain Knowledge:\n"
            f"{specific_knowledge}\n\n"
            "Task: Convert the user's natural language question into a SQL query.\n"
            "Output: Return only the query string.\n\n"
            "The user's question and corresponding output examples are as follows:\n\n"
            "Example 1\n"
            "Question: Please list the Asian populations of all the residential areas with the bad alias \"URB San Joaquin\".\n"
            "Output: SELECT SUM(T1.asian_population) FROM zip_data AS T1 INNER JOIN avoid AS T2 ON T1.zip_code = T2.zip_code WHERE T2.bad_alias = 'URB San Joaquin'\n\n"
            "Example 2\n"
            "Question: What is the country and state of the city named Dalton?\n"
            "Output: SELECT T2.county FROM state AS T1 INNER JOIN country AS T2 ON T1.abbreviation = T2.state INNER JOIN zip_data AS T3 ON T2.zip_code = T3.zip_code WHERE T3.city = 'Dalton' GROUP BY T2.county\n\n"
            "Example 3\n"
            "Question: How many cities does congressman Pierluisi Pedro represent?\n"
            "Output: SELECT COUNT(DISTINCT T1.city) FROM zip_data AS T1 INNER JOIN zip_congress AS T2 ON T1.zip_code = T2.zip_code INNER JOIN congress AS T3 ON T2.district = T3.cognress_rep_id WHERE T3.first_name = 'Pierluisi' AND T3.last_name = 'Pedro'\n"
        )

    system_content = (
        gql_system if target_lang.lower() == "gql"
        else cypher_system if target_lang.lower() == "cypher"
        else sql_system
    )

    if prompt_style == "zeroshot":
        system_content = system_content.split(
            "\nThe user's question and corresponding output examples are as follows:", 1
        )[0].rstrip()

    # print(system_content)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": (nl_question or "").strip()},
    ]


def detect_prompt_style(system_content: str) -> str:
    if not system_content:
        return "unknown-shot"
    has_examples = bool(re.search(r"\bExample\s+\d+\b", system_content, flags=re.IGNORECASE))
    has_qa_pairs = "Question:" in system_content and "Output:" in system_content
    return "few-shot" if has_examples and has_qa_pairs else "zero-shot"


def infer_prompt_style(
    target_lang: str,
    schema_text: str = "",
    graph_name: str | None = None,
    prompt_style: str = "fewshot",
) -> str:
    supported_targets = {"cypher", "gql", "sql"}
    if (target_lang or "").lower() not in supported_targets:
        return "unknown-shot"

    messages = build_prompt(
        nl_question="",
        specific_knowledge="",
        schema_text=schema_text,
        target_lang=target_lang,
        graph_name=graph_name,
        prompt_style=prompt_style,
    )
    return detect_prompt_style(messages[0]["content"])


def strip_markdown_fences(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    text = re.sub(r"(?is)^<think>.*", "", text).strip()
    # Remove a leading and trailing Markdown code fence.
    text = re.sub(r"^```(?:cypher|gql|sql|iso-gql)?\s*", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text.strip())
    # Remove any remaining fence markers defensively.
    text = text.replace("```", "").strip()
    return text


def ensure_graph_clause_for_gql(query: str, graph_name: str) -> str:
    q = (query or "").lstrip()
    if not q:
        return q
    if re.match(r"(?i)^\s*GRAPH\s+\S+", q):
        return q
    # Prefix GRAPH when the model omitted it.
    return f"GRAPH {graph_name}\n{q}"


# === 3) call one instance (with retries/backoff) ===
def call_single_instance(
    client,
    idx,
    instance_id,
    question,
    knowledge,
    schema_text,
    model,
    target_lang,
    graph_name,
    max_retries=3,
    timeout=30,
    temperature=0.0,
    max_tokens=512,
    prompt_style="fewshot",
    extra_body=None,
):
    # Avoid calling .strip() on a missing question.
    if not question or not str(question).strip():
        return {
            "idx": idx,
            "instance_id": instance_id,
            "question": question,
            "target_lang": target_lang,
            "generated_query": None,
            "error": "Empty question field (initial_question/initial_nl/level_1/level_2/level_3 not found or blank).",
        }

    for attempt in range(1, max_retries + 1):
        start_time = time.time()
        try:
            messages = build_prompt(
                nl_question=str(question),
                specific_knowledge=knowledge or "",
                schema_text=schema_text,
                target_lang=target_lang,
                graph_name=graph_name,
                prompt_style=prompt_style,
            )

            # completion = client.chat.completions.create(
            #     model=model,
            #     messages=messages,
            #     temperature=temperature,
            #     extra_body={"enable_thinking": True},
            #     timeout=timeout,
            # )

            create_kwargs = dict(
                model=model,
                messages=messages,
                extra_body=(extra_body or {}),
                timeout=timeout,
            )

            # OpenAI's gpt-5 / o-series reasoning models reject `max_tokens`
            # (need `max_completion_tokens`) and only accept the default
            # temperature. Detect by model id and adjust accordingly.
            model_l = (model or "").lower()
            is_openai_reasoning = (
                model_l.startswith("gpt-5")
                or model_l.startswith("o1")
                or model_l.startswith("o3")
                or model_l.startswith("o4")
            )
            if is_openai_reasoning:
                create_kwargs["max_completion_tokens"] = max_tokens
            else:
                create_kwargs["max_tokens"] = max_tokens

            # Some models (e.g. Anthropic Opus 4.8 via the OpenAI-compat layer,
            # or OpenAI gpt-5/o-series) reject a custom `temperature`; omit it.
            if temperature is not None and not is_openai_reasoning:
                create_kwargs["temperature"] = temperature

            completion = client.chat.completions.create(**create_kwargs)

            text = completion.choices[0].message.content or ""
            text = strip_markdown_fences(text)

            # total_tokens = completion.usage.total_tokens
            # prompt_tokens = completion.usage.prompt_tokens
            # completion_tokens = completion.usage.completion_tokens

            # print(f"[TOKENS]: {total_tokens} (prompt: {prompt_tokens}, completion: {completion_tokens})")

            if target_lang.lower() == "gql":
                text = ensure_graph_clause_for_gql(text, graph_name)

            return {
                "idx": idx,
                "instance_id": instance_id,
                "question": question,
                "external_knowledge": knowledge or "",
                "target_lang": target_lang,
                "generated_query": text,
                "elapsed_seconds": round(time.time() - start_time, 3),
                "completion_tokens": getattr(completion.usage, "completion_tokens", None) if completion.usage else None,
            }

        except Exception as e:
            if attempt == max_retries:
                return {
                    "idx": idx,
                    "instance_id": instance_id,
                    "question": question,
                    "target_lang": target_lang,
                    "generated_query": None,
                    "error": str(e),
                    "elapsed_seconds": round(time.time() - start_time, 3),
                }

            # Exponential backoff with jitter.
            sleep_s = min(8.0, (2 ** (attempt - 1)) * 1.0) + random.uniform(0, 0.3)
            time.sleep(sleep_s)


# === 4) parallel runner ===
def call_qwen_api_parallel(
    instances,
    schema_text,
    api_key,
    target_lang,
    graph_name,
    model,
    max_workers=1,
    max_retries=3,
    timeout=600,
    temperature=0.0,
    max_tokens=512,
    prompt_style="fewshot",
    base_url=None,
    extra_body=None,
):
    client = OpenAI(api_key=api_key, base_url=base_url)
    futures, results = [], []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for i, item in enumerate(instances):
            futures.append(
                executor.submit(
                    call_single_instance,
                    client,
                    i,
                    item.get("instance_id"),
                    item.get("question"),
                    item.get("knowledge", ""),
                    schema_text,
                    model,
                    target_lang,
                    graph_name,
                    max_retries,
                    timeout,
                    temperature,
                    max_tokens,
                    prompt_style,
                    extra_body,
                )
            )

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc=f"Generating {target_lang.upper()}",
        ):
            results.append(future.result())

    results.sort(key=lambda x: x["idx"])
    for r in results:
        r.pop("idx", None)
    return results


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Text-to-Cypher / Text-to-Spanner-GQL Generator")

    parser.add_argument("--target", type=str, choices=["cypher", "gql", "sql"], required=True,
                        help="Target language: cypher, gql, or sql")


    # GQL requires a graph name.
    parser.add_argument("--graph_name", type=str, default=None,
                        help="Spanner Graph name (required when --target gql), used as: GRAPH <graph_name>")

    parser.add_argument("--output_file", type=str, default=None,
                        help="Output JSON path. If None, auto-generated near input file.")

    parser.add_argument("--model", type=str, default="qwen3.7-max", help="Model name")
    parser.add_argument("--max_workers", type=int, default=5, help="Thread pool workers")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout (seconds)")
    parser.add_argument("--max_retries", type=int, default=3, help="Retry times per item")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    parser.add_argument("--max_tokens", type=int, default=512, help="Maximum generated tokens per request")
    parser.add_argument(
        "--prompt_style",
        choices=["zeroshot", "fewshot"],
        required=True,
        help="Required: omit examples for zeroshot or include examples for fewshot.",
    )

    parser.add_argument("--corpus_path", type=str, required=True,
                        help="Path to the input corpus JSON or JSONL file.")
    parser.add_argument("--schema_file", type=str, default=None,
                        help="Path to graph schema file (.json/.txt/.sql); required for Cypher and GQL.")
    parser.add_argument("--sqlite_db", type=str, default=None,
                        help="Path to SQLite DB file; required for SQL.")
    parser.add_argument("--input_field", type=str, default=None,
                        help=(
                            "Question variant: initial_question, level_1, level_2, level_3, "
                            "or level_3_plus_external_knowledge. Only the last variant injects "
                            "external knowledge and uses level_3 as its question."
                        ))
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N input items. Useful for quick tests.")
    parser.add_argument("--base_url", type=str, default=None,
                        help="OpenAI-compatible base URL (falls back to LLM_BASE_URL, then DashScope).")
    parser.add_argument("--api_key", type=str, default=None,
                        help="API key override (prefer the LLM_API_KEY environment variable).")

    args = parser.parse_args()


    # Resolve credentials and provider configuration at runtime.
    api_key = args.api_key or os.environ.get("LLM_API_KEY")

    # base_url resolution:
    #   - if --base_url is passed at all (even as ""), it wins; "" -> None (OpenAI client default)
    #   - else fall back to env LLM_BASE_URL, then the default Qwen endpoint
    if args.base_url is not None:
        base_url = args.base_url or None
    else:
        base_url = os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL

    # Disable / minimize "thinking" per provider so reasoning tokens don't eat
    # the output budget and truncate the query:
    #   - dashscope (Qwen): enable_thinking=False
    #   - Gemini (generativelanguage): reasoning_effort="none" (thinking off)
    #   - OpenAI gpt-5.6 / o-series: reasoning_effort="none" (thinking off)
    # Anthropic Opus 4.8 already runs without thinking by default -> nothing to send.
    _bu = (base_url or "")
    _model_l = (args.model or "").lower()
    _is_openai_reasoning = (
        _model_l.startswith("gpt-5") or _model_l.startswith("o1")
        or _model_l.startswith("o3") or _model_l.startswith("o4")
    )
    _bu_l = _bu.lower()
    if "dashscope" in _bu_l:
        extra_body = {"enable_thinking": False}
    elif "generativelanguage" in _bu_l:
        extra_body = {"reasoning_effort": "none"}
    elif "deepseek" in _bu_l or "moonshot" in _bu_l or "kimi.ai" in _bu_l:
        # DeepSeek V4 and Moonshot Kimi use the OpenAI-compatible switch below
        # to disable thinking and avoid spending the output budget on reasoning.
        extra_body = {"thinking": {"type": "disabled"}}
    elif _is_openai_reasoning:
        extra_body = {"reasoning_effort": "none"}
    else:
        extra_body = None

    # Anthropic (Opus 4.8 via OpenAI-compat) rejects `temperature`; omit it there.
    temperature = None if "anthropic" in (base_url or "") else args.temperature

    schema_file = args.schema_file
    input_file = args.corpus_path
    sqlite_db = args.sqlite_db

    if not api_key or not api_key.strip():
        raise ValueError("Missing API key: set LLM_API_KEY or pass --api_key")

    if args.target.lower() == "sql" and not sqlite_db:
        raise ValueError("--sqlite_db is required when --target sql")
    if args.target.lower() != "sql" and not schema_file:
        raise ValueError("--schema_file is required for Cypher and GQL")

    # gql needs graph_name
    if args.target.lower() == "gql":
        if not args.graph_name or not args.graph_name.strip():
            raise ValueError("--graph_name is required when --target gql")
        graph_name = args.graph_name.strip()
    else:
        graph_name = args.graph_name.strip() if args.graph_name else "UNUSED"

    # load schema
    if args.target.lower() == "sql":
        print(f"[SQL] Loading schema from SQLite DB: {sqlite_db}")
        schema_text = sqlite_schema_to_text(sqlite_db)
    else:
        print(f"[{args.target.upper()}] Loading Schema from: {schema_file}")
        if schema_file.endswith(".json"):
            with open(schema_file, "r", encoding="utf-8-sig") as f:
                schema_json = json.load(f)
            schema_text = schema_to_text(schema_json)
        else:
            with open(schema_file, "r", encoding="utf-8") as f:
                schema_text = f.read()


    # load questions (JSON array; also supports JSONL fallback)
    print(f"Loading Questions from: {input_file}")
    instances = []

    def load_input_items(path: str):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return []
        if content.lstrip().startswith("["):
            return json.loads(content)
        items = []
        for line in content.splitlines():
            if line.strip():
                items.append(json.loads(line))
        return items

    input_items = load_input_items(input_file)
    if args.limit is not None:
        if args.limit < 0:
            raise ValueError("--limit must be >= 0")
        input_items = input_items[:args.limit]

    for item in input_items:
        i_id = item.get("instance_id") or item.get("id")
        question = None
        use_external_knowledge = (
            args.input_field == "level_3_plus_external_knowledge"
        )
        question_field = "level_3" if use_external_knowledge else args.input_field

        if question_field:
            question = item.get(question_field)
        if not question:
            question = (
                item.get("new_initial_question")
                or item.get("initial_question")
                or item.get("initial_nl")
                or item.get("level_1")
                or item.get("level_2")
                or item.get("level_3")
                or item.get("question")
            )

        # Experimental design:
        #   initial_question / level_1 / level_2 / level_3 -> no knowledge
        #   level_3_plus_external_knowledge -> level_3 question + knowledge
        specific_know = ""
        if use_external_knowledge:
            specific_know = (
                item.get("external_knowledge", "")
                or item.get("evidence", "")
                or ""
            )

        instances.append({
            "instance_id": i_id,
            "question": question,
            "knowledge": specific_know,
            "_raw": item,
        })


    print(f"Ready: {len(instances)} items | target={args.target.upper()}"
          + (f" | GRAPH {graph_name}" if args.target.lower() == "gql" else ""))

    results = call_qwen_api_parallel(
        instances=instances,
        schema_text=schema_text,
        api_key=api_key,
        target_lang=args.target,
        graph_name=graph_name,
        model=args.model,
        max_workers=args.max_workers,
        max_retries=args.max_retries,
        timeout=args.timeout,
        temperature=temperature,
        max_tokens=args.max_tokens,
        prompt_style=args.prompt_style,
        base_url=base_url,
        extra_body=extra_body,
    )

    # output path
    if not args.output_file:
        base_name = os.path.basename(input_file).rsplit(".", 1)[0]
        out_dir = os.path.dirname(os.path.abspath(input_file))
        safe_model = args.model.replace("/", "_")
        prompt_style = infer_prompt_style(args.target, schema_text, graph_name, args.prompt_style)

        args.output_file = os.path.join(
            out_dir,
            f"{base_name}_generated_{args.target}_{safe_model}_{prompt_style}.json"
        )

    # merge generated results back to original input items
    merged = []
    for inst, gen in zip(instances, results):
        raw = dict(inst.get("_raw") or {})

        # Preserve the original record and add generation metadata.
        raw["external_knowledge"] = raw.get("external_knowledge", "") or ""
        raw["target_lang"] = args.target
        raw["generated_query"] = gen.get("generated_query")
        raw["elapsed_seconds"] = gen.get("elapsed_seconds")
        raw["completion_tokens"] = gen.get("completion_tokens")

        if "error" in gen:
            raw["error"] = gen["error"]

        merged.append(raw)

    with open(args.output_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\nDone! Results saved to: {args.output_file}")
    if results:
        print("\nSample Generated Query:\n")
        print(results[0].get("generated_query"))
