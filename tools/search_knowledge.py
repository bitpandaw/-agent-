"""RAG 检索工具。"""

import time
from typing import Any

from tools._result import make_result


def search_knowledge(action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """本地单进程检索：Chroma + Embedding + KG + Reranker 均在进程内执行。"""
    start: float = time.perf_counter()
    query: str = action["query"]
    from rag.retrieve_local import retrieve as retrieve_local

    results: list[dict[str, Any]] = retrieve_local(query)
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
