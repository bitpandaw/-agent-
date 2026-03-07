"""工具注册表与 make_result。"""

from typing import Any, Callable

from tools._result import make_result
from tools.calculator import calculator
from tools.query_qa_records import query_qa_records
from tools.search_article_graph import search_article_graph
from tools.search_knowledge import search_knowledge

ToolFunc = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


__all__ = ["TOOL_REGISTRY", "make_result"]

TOOL_REGISTRY: dict[str, ToolFunc] = {
    "search_knowledge": search_knowledge,
    "query_qa_records": query_qa_records,
    "search_article_graph": search_article_graph,
    "calculator": calculator,
}
