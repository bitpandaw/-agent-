# tool_registry.py
import sqlite3
import time
from typing import Any, Callable, Dict

import httpx

from config.config_loader import config

_embedding_model = None


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

# Tool registry
TOOL_REGISTRY: Dict[str, ToolFunc] = {
    "search_knowledge": search_knowledge,
    "calculator": calculator,
    "query_fault_history": query_fault_history,
}
