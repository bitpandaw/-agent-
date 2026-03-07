"""RAG 检索工具：通过 HTTP 调用 RAG 服务 /retrieve。"""

import os
import time
from typing import Any

import httpx

from config.config_loader import config
from tools._result import make_result

RAG_URL: str = os.environ.get("RAG_URL", "http://localhost:8010")


def search_knowledge(action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """调用 RAG HTTP /retrieve 接口，返回检索到的文档。"""
    start: float = time.perf_counter()
    query: str = action.get("query") or ""
    if not query:
        return make_result(
            False, "E_RAG_PARAM", "缺少 query 参数", None,
            (time.perf_counter() - start) * 1000
        )
    use_reranker: bool = (config.get("reranker") or {}).get("enabled", False)
    try:
        resp: httpx.Response = httpx.post(
            f"{RAG_URL.rstrip('/')}/retrieve",
            json={"query": query, "use_reranker": use_reranker},
            timeout=60,
        )
        resp.raise_for_status()
        results: list[dict[str, Any]] = resp.json()
    except httpx.RequestError as e:
        return make_result(
            False, "E_RAG_CONNECT", f"RAG 服务连接失败: {e}", None,
            (time.perf_counter() - start) * 1000
        )
    except httpx.HTTPStatusError as e:
        return make_result(
            False, "E_RAG_HTTP", f"RAG 请求失败: {e.response.status_code}", None,
            (time.perf_counter() - start) * 1000
        )
    if not results or not isinstance(results, list):
        return make_result(
            False, "E_RAG_DOC", "没有找到相关文档", None,
            (time.perf_counter() - start) * 1000
        )
    out: str = "Found relevant documents:\n\n"
    for index, item in enumerate(results, start=1):
        score: float = item.get("score", 0.0)
        text: str = item.get("text", "") or ""
        out += f"rank: {index} score: {score} text: {text}\n"
    return make_result(
        True, "S_RAG_QUERY", "查询成功", out,
        (time.perf_counter() - start) * 1000
    )
