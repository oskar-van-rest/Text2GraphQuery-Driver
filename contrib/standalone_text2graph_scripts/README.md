# Standalone prediction and evaluation reference scripts

This directory contains a directly runnable prediction script and three
evaluation scripts retained as reference implementations. No credentials,
cloud resource identifiers, or machine-specific absolute paths are embedded in
these files.

## Contents

- `call_qwen_api_both_new.py`: generates Cypher, GQL, or SQL with an
  OpenAI-compatible API.
- `reference/ea_gql.py`: reference execution-accuracy evaluator for Google
  Cloud Spanner GQL.
- `reference/ea_cypher.py`: reference execution-accuracy evaluator for
  Cypher/TuGraph through the Neo4j Bolt driver.
- `reference/evaluate_gql.py`: reference grammar, structural similarity, and
  Google BLEU wrapper using this repository's vendored evaluator.

The files under `reference/` document the evaluation approach used in the
experiments. Consumers should adapt them to their own database lifecycle,
authentication, timeout, result-normalization, and error-handling requirements.

## Installation

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r contrib/standalone_text2graph_scripts/requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r contrib\standalone_text2graph_scripts\requirements.txt
```

## Prediction

Set the API key in an environment variable. Do not put it in the script or
commit it to a configuration file.

Linux/macOS:

```bash
export LLM_API_KEY="your-api-key"
```

Windows PowerShell:

```powershell
$env:LLM_API_KEY="your-api-key"
```

The default endpoint is the DashScope OpenAI-compatible endpoint. A different
provider can be selected with `LLM_BASE_URL` or `--base_url`.

GQL example:

```bash
python contrib/standalone_text2graph_scripts/call_qwen_api_both_new.py \
  --target gql \
  --corpus_path data/questions.json \
  --schema_file data/schema.txt \
  --graph_name my_graph \
  --model qwen-plus \
  --prompt_style fewshot \
  --output_file output/predictions.json
```

Cypher example:

```bash
python contrib/standalone_text2graph_scripts/call_qwen_api_both_new.py \
  --target cypher \
  --corpus_path data/questions.json \
  --schema_file data/schema.txt \
  --model qwen-plus \
  --prompt_style zeroshot
```

SQL requires `--sqlite_db` instead of `--schema_file`:

```bash
python contrib/standalone_text2graph_scripts/call_qwen_api_both_new.py \
  --target sql \
  --corpus_path data/questions.json \
  --sqlite_db data/database.sqlite \
  --model qwen-plus
```

The input may be a JSON array or JSONL. Each record should contain `id` or
`instance_id`, plus a question field. By default, the script checks
`new_initial_question`, `initial_question`, `initial_nl`, `level_1`, `level_2`,
`level_3`, and `question` in that order. Use `--input_field` to select another
field explicitly. Generated queries are written to `generated_query` while the
original record fields are preserved.

Run `python call_qwen_api_both_new.py --help` for all concurrency, retry, token, and
provider options.

## Reference: GQL execution accuracy

Authenticate with Google Application Default Credentials using the mechanism
appropriate for the execution environment, then supply all resource IDs at
runtime:

```bash
python contrib/standalone_text2graph_scripts/reference/ea_gql.py \
  --project-id PROJECT_ID \
  --instance-id INSTANCE_ID \
  --database-id DATABASE_ID \
  --input-path output/predictions.json
```

Optional failure-report paths can be supplied with
`--output-failed-path`, `--output-failed-gold-path`, and
`--output-gold-valid-ids-path`. When the first two are omitted, reports are
written next to the input file.

## Reference: Cypher execution accuracy

Set the database password outside the source file:

```bash
export TUGRAPH_PASSWORD="your-password"
```

Then run:

```bash
python contrib/standalone_text2graph_scripts/reference/ea_cypher.py \
  --input-path output/predictions.json \
  --database graph_database \
  --uri bolt://localhost:7687 \
  --user admin
```

The field names are configurable through `--id-field`, `--gold-field`, and
`--prediction-field`. Container restart behavior is specific to the reference
environment; use `--no-auto-restart` when the evaluator must not manage a local
container.

## Reference: grammar, similarity, and Google BLEU

The wrapper defaults to the evaluator already stored under
`tools/eval_similarity_grammar`:

```bash
python contrib/standalone_text2graph_scripts/reference/evaluate_gql.py \
  --json-file output/predictions.json \
  --language gql
```

It infers `generated_query` as the prediction and prefers `gql` as the gold
field. Use `--prediction-key` and `--gold-key` when the input uses different
names. Grammar and similarity depend on the vendored evaluator and its parser
dependencies; Google BLEU uses the Hugging Face `evaluate` package.

## Security notes

- Supply API keys and database passwords through environment variables or a
  secret manager.
- Do not commit `.env` files, cloud service-account JSON, generated prediction
  data, or evaluator logs.
- Review database permissions before running execution-based evaluation because
  it executes both gold and predicted queries.
