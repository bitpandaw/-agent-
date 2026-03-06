# tool_registry.py
import sqlite3
import time
from typing import Any, Callable, Dict, Optional

import httpx
from neo4j import GraphDatabase

from config.config_loader import config

_embedding_model: Optional[Any] = None


def get_embedding_model() -> Any:
    """懒加载 SentenceTransformer，供 experiments 等本地脚本使用。"""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(
            config["embedding"]["model_name"],
            cache_folder=config["embedding"].get("cache_dir", ".hf_cache"),
        )
    return _embedding_model
_neo4j_driver: Optional[Any] = None


def _get_neo4j_driver() -> Any:
    global _neo4j_driver
    if _neo4j_driver is None:
        neo4j_cfg: Dict[str, Any] = config["neo4j"]
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
    start: float = time.perf_counter()
    expression: str = action["expression"]
    try:
        payload = eval(expression, {"__builtins__": {}}, {})
        return make_result(True, "S_ADD", "add success", payload, (time.perf_counter() - start) * 1000)
    except Exception as e:
        return make_result(
            False, "E_ADD", f"add failed: {e}", None, (time.perf_counter() - start) * 1000
        )


def search_knowledge(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    start: float = time.perf_counter()
    query: str = action["query"]
    max_retries: int = 3
    rag: Dict[str, Any] = config["rag"]
    results: list[Dict[str, Any]] = []
    for attempt in range(max_retries):
        try:
            resp: httpx.Response = httpx.post(
                "http://localhost:8010/retrieve",
                json={"query": query},
                timeout=30,
            )
            resp.raise_for_status()
            raw: Any = resp.json()
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
    result: str = "Found relevant documents:\n\n" + "\n\n---\n\n"
    for index, item in enumerate(results, start=1):
        result += f"rank: {index} score: {item['score']} text: {item['text']}\n"
    return make_result(
        True, "S_RAG_QUERY", "查询到ChromaDB", result,
        (time.perf_counter() - start) * 1000
    )


def query_qa_records(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    start: float = time.perf_counter()
    db_path: str = config["paths"]["db"]
    article_title: str = action.get("article_title") or ""
    keyword: str = action.get("keyword") or ""

    sql: str = "SELECT question, answer, article_titles, created_at FROM qa_records "
    params: tuple = ()
    if article_title and keyword:
        sql += "WHERE article_titles LIKE ? AND (question LIKE ? OR answer LIKE ?)"
        params = (f"%{article_title}%", f"%{keyword}%", f"%{keyword}%")
    elif article_title:
        sql += "WHERE article_titles LIKE ?"
        params = (f"%{article_title}%",)
    elif keyword:
        sql += "WHERE question LIKE ? OR answer LIKE ?"
        params = (f"%{keyword}%", f"%{keyword}%")
    else:
        sql += "LIMIT 10"

    with sqlite3.connect(db_path) as conn:
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(sql, params)
        rows: list[tuple[Any, ...]] = cursor.fetchall()
        if not rows:
            return make_result(
                False, "F_DB_QUERY", "未找到匹配数据", None,
                (time.perf_counter() - start) * 1000,
            )
        lines: list[str] = [f"找到{len(rows)}条记录："]
        for i, (q, a, titles, dt) in enumerate(rows, 1):
            q_short: str = (q[:60] + "...") if len(str(q)) > 60 else str(q)
            lines.append(f"{i}. Q: {q_short} | A: {a} | 文章: {titles} | {dt}")
        return make_result(
            True, "S_DB_QUERY", "找到匹配数据", "\n".join(lines),
            (time.perf_counter() - start) * 1000,
        )


def search_article_graph(
    action: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    start: float = time.perf_counter()
    article_title: str = action.get("article_title") or ""
    query: str = action.get("query") or ""

    if article_title:
        cypher: str = (
            "MATCH (a:Article {title: $title})-[:CONTAINS]->(s:Sentence) "
            "RETURN a.title AS article, s.text AS sentence "
            "LIMIT 15"
        )
        params: Dict[str, str] = {"title": article_title}
    elif query:
        cypher = (
            "MATCH (a:Article)-[:CONTAINS]->(s:Sentence) "
            "WHERE s.text CONTAINS $query OR a.title CONTAINS $query "
            "RETURN a.title AS article, s.text AS sentence "
            "LIMIT 15"
        )
        params = {"query": query}
    else:
        return make_result(
            False, "E_KG_PARAM", "需要提供 article_title 或 query 参数", None,
            (time.perf_counter() - start) * 1000,
        )

    try:
        driver: Any = _get_neo4j_driver()
        with driver.session() as session:
            result: Any = session.run(cypher, **params)
            records: list[Dict[str, Any]] = result.data()
        if not records:
            return make_result(
                False, "E_KG_EMPTY", "未找到相关图谱数据", None,
                (time.perf_counter() - start) * 1000,
            )
        lines: list[str] = [
            f"[{r['article']}] {r['sentence'][:120]}..." for r in records
        ]
        return make_result(
            True, "S_KG", f"查询到{len(records)}条", "\n".join(lines),
            (time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return make_result(
            False, "E_KG_QUERY", f"知识图谱查询失败: {e}", None,
            (time.perf_counter() - start) * 1000,
        )


# Tool registry
TOOL_REGISTRY: Dict[str, ToolFunc] = {
    "search_knowledge": search_knowledge,
    "query_qa_records": query_qa_records,
    "search_article_graph": search_article_graph,
    "calculator": calculator,
}
