# Text2Graph Evaluation Driver

This is a modular, **Object-Oriented Programming (OOP)** based experimental framework designed for **Text-to-Graph (Text2Cypher/GQL)** tasks. The system covers the entire pipeline from natural language question transformation to query execution, validation, and multi-dimensional metric evaluation.

The project supports integration with **Qwen** and other Large Language Models (LLMs) for prediction, connects to graph databases (**TuGraph**, **Google Spanner**) and relational databases (**SQLite**) for Execution Accuracy (EA) verification, and utilizes external tools for in-depth grammatical and structural analysis.

---

## Key Features

* **Full Pipeline Control**: Supports flexible toggling between the **Prediction Phase** (LLM query generation) and the **Evaluation Phase** (metrics calculation).
* **LLM Integration**: Built-in interface compatible with the OpenAI SDK format (default configuration targets AliCloud DashScope/Qwen).
* **Multi-Database Support**:
* **TuGraph**: Connects via Bolt protocol.
* **Google Spanner**: Supports GQL query validation for cloud-native distributed graph databases.
* **SQLite**: Supports traditional SQL execution for cross-paradigm comparisons.


* **Multi-Dimensional Metrics**:
* **Execution Accuracy (EA)**: Compares results returned by the database against gold standards.
* **Google BLEU**: Text-level N-gram similarity.
* **External Metrics**: Integration with external tools to calculate **Grammar Correctness** and **Structural Similarity**.


* **Clean OOP Architecture**: Uses abstract base classes (Drivers), making it easy to extend with new model interfaces or database adapters.

---

## Project Structure

```text
\gql-generation-driver
├─ driver/                  # Abstract Interface Definitions
├─ example_data/            # Sample Input Data (JSON)
├─ experiment/              # Configuration Files
├─ impl/                    # Core Implementation Layer
│  ├─ db_driver/            # Database Adapters (TuGraph, Spanner, SQLite)
│  ├─ evaluation/           # Metric Implementations
│  └─ text2graph_system/    # LLM System Logic
├─ tools/                   # External Tools (Evaluation plugins, etc.)
├─ output/                  # Prediction Results Directory
├─ evaluation_detail/       # Detailed Evaluation Reports
├─ requirements.txt         # Project Dependencies
└─ run_pipeline.py          # Main Entry Point

```

---

## Environment Setup

### 1. Install Dependencies

Ensure Python version is >= 3.8. Run the following in the project root:

```bash
pip install -r requirements.txt

```

### 2. Set PYTHONPATH

To ensure Python correctly resolves module imports within the project structure, set the `PYTHONPATH` before execution.

**Windows (PowerShell):**

```powershell
$env:PYTHONPATH="."

```

**Windows (CMD):**

```dos
set PYTHONPATH=.

```

**Linux/macOS (Bash/Zsh):**

```bash
export PYTHONPATH=.

```

---

## Configuration Guide

The main configuration file is located at `experiment/test_config.json`. Key fields are described below:

```json
{
  "pipeline": {
    "run_prediction": true,                                       // Toggle LLM prediction
    "run_evaluation": true                                        // Toggle metrics calculation
  },
  "data": {
    "input_path": "example_data/Social_Network_Twitter/Cypher/Social_Network_Twitter_cypher.json",
    "output_path": "output/test_result.json"
  },
  "prediction": {
    "api_key": "PLACEHOLDER_FOR_API_KEY",                       // Your LLM API Key
    "base_url": "PLACEHOLDER_FOR_BASE_URL",                     // Model API Endpoint
    "model": "qwen-plus",                                       // Model Name
    "schema_path": "example_data/Social_Network_Twitter/Cypher/schema.txt",
    "target_lang": "cypher",                                    // Options: cypher, gql, sql
    "mode": "zeroshot",                                                     
    "graph_name": "social_network_twitter",
    "max_workers": 5,                                           // Concurrency for API calls
    "temperature": 0.0,
    "level_fields": [                                           // Dynamic mapping of Input vs Output fields
      ["initial_question", "initial_query"],
      ["level_1", "level_1_query"],
      ["level_2", "level_2_query"],
      ["level_3", "level_3_query"],
      ["level3_with_ext", "level_3_external_knowledge_query"]
    ]
  },
  "evaluation": {
    "tugraph": {
      "db_uri": "bolt://localhost:7687",                        // TuGraph Connection URI
      "db_user": "admin",
      "db_pass": "PLACEHOLDER_FOR_DB_PASS"
    },
    "dbgpt_root": "tools/eval_similarity_grammar",              // Root for external eval tools
    "spanner": {                                                // Google Spanner Config
      "project_id": "PLACEHOLDER_FOR_PROJECT_ID",
      "instance_id": "PLACEHOLDER_FOR_INSTANCE_ID",
      "database_id": "PLACEHOLDER_FOR_DATABASE_ID"
    }, 
    "sqlite": {                                                 // SQLite Config
      "db_path": "example_data/SQLite/disney.sqlite"
    }
  }
}

```

---

## Usage Guide

### Method A: Run with Default Configuration

```bash
python run_pipeline.py

```

### Method B: Specify Custom Configuration

Use the `--config` argument to point to a specific config file:

```bash
python run_pipeline.py --config experiment/debug_config.json

```

---

## Data Format Description

### About Example Data (`example_data/geography`)

The sample file `geography_5_csv_files_08051006_corpus_seeds.json` uses **Cypher** as the default language for gold standard queries. The accompanying `.csv` and `import_config.json` files are specifically formatted for batch import into **TuGraph DB**.

### Input Data Format

Each entry includes the database name, the original question, multi-level reasoning questions, and optional external knowledge:

```json
{
  "id": "unique_identifier",
  "database": "database_name",
  "initial_question": "Original natural language question",
  "gold_query": "Gold standard Cypher/GQL query",
  "level_1": "Level 1 (Coarse-grained reasoning) question",
  "level_2": "Level 2 (Structured reasoning) question",
  "level_3": "Level 3 (Sub-goal planning) question",
  "external_knowledge": "Knowledge from outside sources (Encyclopedia, etc.)",
  "difficulty": "easy / medium / hard",
  "source": "data_source"
}

```

### Predicted Output Format

The model generates predicted queries for each level, saved in `data.output_path`:

```json
{
  "id": "Unique Identifier",
  "database": "Database Name",
  "initial_question": "Original Natural Language Question",
  "gold_query": "Correct Cypher/GQL corresponding to the original natural language question",
  "level_1": "Level 1 (Coarse-grained Reasoning) Question",
  "level_2": "Level 2 (Structured Reasoning) Question",
  "level_3": "Level 3 (Sub-goal Planning) Question",
  "level_4": "Level 4 (Final Reasoning) Question",
  "external_knowledge": "Knowledge depending on sources outside the database (e.g., encyclopedia, common facts, can be empty)",
  "difficulty": "Question Difficulty (easy / medium / hard)",
  "source": "Data Source",
  "initial_query": "Model Predicted Query Statement",
  "level_1_query": "Model Predicted Query Statement",
  "level_2_query": "Model Predicted Query Statement",
  "level_3_query": "Model Predicted Query Statement",
  "level_3_external_knowledge_query": "Model Predicted Query Statement"
}

```

### Evaluation Output Format

Evaluation produces the following metrics for each reasoning level:

* **EA (Execution Accuracy)**
* **Grammar (Syntactic Validity)**
* **Similarity (Structural Matching)**
* **Google BLEU (Textual Similarity)**

Reports are saved in `evaluation_detail/execution_results/` as level-specific JSON files (e.g., `level_1_results.json`):

```json
[
  {
    "instance_id": "unique_identifier",
    "gold_query": "Standard answer query",
    "pred_query": "Model predicted query",
    "metrics": {
      "ea": 1.0,
      "grammar": 1.0,
      "similarity": 0.9212
    }
  }
]

```