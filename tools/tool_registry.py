# tool_registry.py
import sqlite3
import time
from typing import Any, Callable, Dict
from neo4j import GraphDatabase
import httpx

from config.config_loader import config

_embedding_model = None


def get_embedding_model():
    """懒加载 SentenceTransformer，供 experiments 等本地脚本使用。"""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(
            config["embedding"]["model_name"],
            cache_folder=config["embedding"].get("cache_dir", ".hf_cache"),
        )
    return _embedding_model
_neo4j_driver = None


def _get_neo4j_driver():
    global _neo4j_driver
    if _neo4j_driver is None:
        neo4j_cfg = config["neo4j"]
        _neo4j_driver = GraphDatabase.driver(
            neo4j_cfg["uri"],
            auth=(neo4j_cfg["user"], neo4j_cfg["password"]),
        )
    return _neo4j_driver

def make_result(
    ok: bool, code: str, message: str, payload: Any, latency_ms: float
) -> Dict[str, Any]:
    return {
        "ok": ok,
        "code": code,
        "message": message,
        "payload": payload,
        "latency_ms": round(latency_ms, 2),
    }


ToolFunc = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


def calculator(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    expression = action["expression"]
    try:
        payload = eval(expression, {"__builtins__": {}}, {})
        return make_result(True, "S_ADD", "add success", payload, (time.perf_counter() - start) * 1000)
    except Exception as e:
        return make_result(
            False, "E_ADD", f"add failed: {e}", None, (time.perf_counter() - start) * 1000
        )


def search_knowledge(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    query = action["query"]
    max_retries = 3
    rag = config["rag"]
    for attempt in range(max_retries):
        try:
            resp = httpx.post(
                "http://rag:8010/retrieve",   # 或 localhost:8010，取决于你本地如何启动 RAG
                json={"query": query},
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json()
            # RAG 返回的是 [{"doc_id", "text", "score"}, ...]，和原来 retrieve_context 一致
            results = raw if isinstance(raw, list) else raw.get("results", raw)
            break
        except Exception as e:
            if attempt == max_retries - 1:
                return make_result(
                    False, "E_RAG_QUERY", "查询超时ChromaDB", None,
                    (time.perf_counter() - start) * 1000
                )
            time.sleep(10)
    if not results:
        return make_result(
            False, "E_RAG_DOC", "没有找到文件", None,
            (time.perf_counter() - start) * 1000
        )
    result = "Found relevant documents:\n\n" + "\n\n---\n\n"
    for index, item in enumerate(results, start=1):
        result += f"rank: {index} score: {item['score']} text: {item['text']}\n"
    return make_result(
        True, "S_RAG_QUERY", "查询到ChromaDB", result,
        (time.perf_counter() - start) * 1000
    )


def query_fault_history(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    db_path = config["paths"]["db"]
    params: tuple = ()
    equipment_id = action["equipment_id"]
    fault_type = action["fault_type"]
    sql = "SELECT * FROM fault_records "
    if equipment_id and fault_type:
        sql += "WHERE equipment_id = ? AND fault_type = ?"
        params = (equipment_id, fault_type)
    elif equipment_id and not fault_type:
        sql += "WHERE equipment_id = ?"
        params = (equipment_id,)
    elif not equipment_id and fault_type:
        sql += "WHERE fault_type = ?"
        params = (fault_type,)
    else:
        sql += "LIMIT 10"
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        if not rows:
            return make_result(
                False, "F_DB_QUERY", "未找到匹配数据", None,
                (time.perf_counter() - start) * 1000
            )
        lines = [f"找到{len(rows)}条记录："]
        for i, row in enumerate(rows, 1):
            _, ft, date, sol, hours, eq = row
            lines.append(f"{i}. {eq} - {ft} - {date} - 解决方案：{sol} - 停机{hours}小时")
        return make_result(
            True, "S_DB_QUERY", "找到匹配数据", "\n".join(lines),
            (time.perf_counter() - start) * 1000
        )
def search_knowledge_graph(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    alarm_id = action.get("alarm_id", "")
    query = action.get("query", "")

    if alarm_id:
        cypher = (
            "MATCH (a:Alarm {alarm_id: $alarm_id})-[r]-(n) "
            "RETURN type(r) AS relation, labels(n)[0] AS node_type, "
            "COALESCE(n.name, n.md_id, n.text, n.alarm_id) AS value "
            "LIMIT 20"
        )
        params = {"alarm_id": alarm_id}
    elif query:
        cypher = (
            "MATCH (a:Alarm) WHERE a.alarm_text CONTAINS $query "
            "OR a.description CONTAINS $query "
            "OPTIONAL MATCH (a)-[r]-(n) "
            "RETURN a.alarm_id, a.alarm_text, type(r) AS relation, "
            "labels(n)[0] AS node_type, "
            "COALESCE(n.name, n.md_id, n.text) AS value "
            "LIMIT 30"
        )
        params = {"query": query}
    else:
        return make_result(
            False, "E_KG_PARAM", "需要提供 alarm_id 或 query 参数", None,
            (time.perf_counter() - start) * 1000,
        )

    try:
        driver = _get_neo4j_driver()
        with driver.session() as session:
            result = session.run(cypher, **params)
            records = result.data()
        if not records:
            return make_result(
                False, "E_KG_EMPTY", "未找到相关图谱数据", None,
                (time.perf_counter() - start) * 1000,
            )
        return make_result(
            True, "S_KG", f"查询到{len(records)}条关联", records,
            (time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return make_result(
            False, "E_KG_QUERY", f"知识图谱查询失败: {e}", None,
            (time.perf_counter() - start) * 1000,
        )


# Tool registry
TOOL_REGISTRY: Dict[str, ToolFunc] = {
    "search_knowledge_graph":search_knowledge_graph,
    "search_knowledge": search_knowledge,
    "calculator": calculator,
    "query_fault_history": query_fault_history,
}
