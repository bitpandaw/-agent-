"""Quick diagnostic: test each component of the KG pipeline."""

import json
import sys
import time
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "debug-46c420.log"


def _log(hypothesis: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    import json as _j
    entry = _j.dumps({
        "sessionId": "46c420", "hypothesisId": hypothesis,
        "location": location, "message": message, "data": data,
        "timestamp": int(time.time() * 1000),
    }, ensure_ascii=False)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry + "\n")
    # #endregion


def test_neo4j_package() -> None:
    """H-A: Can we import neo4j?"""
    try:
        from neo4j import GraphDatabase
        _log("H-A", "test_pipeline.py:test_neo4j_package", "neo4j import OK", {"status": "ok"})
    except ImportError as e:
        _log("H-A", "test_pipeline.py:test_neo4j_package", "neo4j import FAILED", {"error": str(e)})


def test_neo4j_connection() -> None:
    """H-B: Can we connect to Neo4j?"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config.config_loader import config
        neo4j_cfg = config["neo4j"]
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            neo4j_cfg["uri"], auth=(neo4j_cfg["user"], neo4j_cfg["password"])
        )
        driver.verify_connectivity()
        _log("H-B", "test_pipeline.py:test_neo4j_connection", "Neo4j connection OK", {
            "uri": neo4j_cfg["uri"], "user": neo4j_cfg["user"]
        })
        driver.close()
    except Exception as e:
        _log("H-B", "test_pipeline.py:test_neo4j_connection", "Neo4j connection FAILED", {
            "error": str(e), "error_type": type(e).__name__
        })


def test_tool_registry_import() -> None:
    """H-C: Can we import tool_registry without crash?"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.tool_registry import TOOL_REGISTRY
        tools = list(TOOL_REGISTRY.keys())
        _log("H-C", "test_pipeline.py:test_tool_registry_import", "tool_registry import OK", {
            "tools": tools
        })
    except Exception as e:
        _log("H-C", "test_pipeline.py:test_tool_registry_import", "tool_registry import FAILED", {
            "error": str(e), "error_type": type(e).__name__
        })


def test_structured_alarms() -> None:
    """H-D: Is structured_alarms.json valid and non-empty?"""
    path = Path(__file__).resolve().parent / "structured_alarms.json"
    if not path.exists():
        _log("H-D", "test_pipeline.py:test_structured_alarms", "File not found", {"exists": False})
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        sample = data[0] if data else {}
        has_fields = all(k in sample for k in ["alarm_id", "components", "machine_data_ids", "referenced_alarms"])
        _log("H-D", "test_pipeline.py:test_structured_alarms", "structured_alarms loaded", {
            "count": len(data),
            "sample_alarm_id": sample.get("alarm_id", ""),
            "has_required_fields": has_fields,
        })
    except json.JSONDecodeError as e:
        _log("H-D", "test_pipeline.py:test_structured_alarms", "JSON parse error (LLM still running?)", {
            "error": str(e)
        })


def test_cypher_syntax() -> None:
    """H-E: Does the Cypher query run without syntax error?"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config.config_loader import config
        from neo4j import GraphDatabase
        neo4j_cfg = config["neo4j"]
        driver = GraphDatabase.driver(
            neo4j_cfg["uri"], auth=(neo4j_cfg["user"], neo4j_cfg["password"])
        )
        cypher = (
            "MATCH (a:Alarm {alarm_id: $alarm_id})-[r]-(n) "
            "RETURN type(r) AS relation, labels(n)[0] AS node_type, "
            "COALESCE(n.name, n.md_id, n.text, n.alarm_id) AS value "
            "LIMIT 5"
        )
        with driver.session() as session:
            result = session.run(cypher, alarm_id="2000")
            records = result.data()
        _log("H-E", "test_pipeline.py:test_cypher_syntax", "Cypher query OK", {
            "records_count": len(records),
            "sample": records[:2] if records else "empty (no data imported yet)"
        })
        driver.close()
    except Exception as e:
        _log("H-E", "test_pipeline.py:test_cypher_syntax", "Cypher query FAILED", {
            "error": str(e), "error_type": type(e).__name__
        })


if __name__ == "__main__":
    print("Running KG pipeline diagnostics...")
    test_neo4j_package()
    test_neo4j_connection()
    test_tool_registry_import()
    test_structured_alarms()
    test_cypher_syntax()
    print(f"Done. Check logs at: {LOG_PATH}")
