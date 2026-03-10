import json
import re
import sqlite3

def sqlite_schema_to_text(db_path: str) -> str:
    """Extract Schema text from a SQLite database"""
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

def schema_to_text(schema_json: dict) -> str:
    """Convert Graph JSON Schema into a text description"""
    lines, vertices, edges = [], [], []
    for item in schema_json.get("schema", []):
        label, type_ = item.get("label"), item.get("type")
        props = ", ".join([f'{p["name"]}: {p["type"]}' for p in item.get("properties", [])])
        if type_ == "VERTEX":
            primary = item.get("primary")
            vertices.append(f"- {label} [primary: {primary}] ({props})" if primary else f"- {label}({props})")
        elif type_ == "EDGE":
            temporal = item.get("temporal")
            edges.append(f"- {label} [temporal: {temporal}] ({props})" if temporal else f"- {label}({props})")

    if vertices: lines.append("Vertex types:\n" + "\n".join(vertices))
    if edges: lines.append("\nEdge types:\n" + "\n".join(edges))
    return "\n".join(lines)

def clean_query(pred: str, target_lang: str = "cypher", graph_name: str = None) -> str:
    if not pred or not isinstance(pred, str):
        return ""
    
    # Remove Markdown code blocks (e.g., ```cypher ... ```)
    pred = re.sub(r"^```(?:cypher|gql|sql|iso-gql)?\s*", "", pred.strip(), flags=re.IGNORECASE)
    pred = re.sub(r"\s*```$", "", pred.strip())

    # Replace newlines with spaces and trim whitespace
    pred = pred.replace('\n', ' ').strip()
    
    # Prepend GRAPH name if the target language is GQL and the keyword is missing
    if target_lang.lower() == "gql" and graph_name:
        if not re.match(r"(?i)^\s*GRAPH\s+", pred):
            pred = f"GRAPH {graph_name} {pred}"
            
    return pred