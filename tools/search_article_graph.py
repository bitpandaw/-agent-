"""知识图谱查询工具。"""

import time
from typing import Any

from tools.drivers import _get_neo4j_driver
from tools._result import make_result


def search_article_graph(
    action: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """查询文章知识图谱。"""
    start: float = time.perf_counter()
    article_title: str = action.get("article_title") or ""
    query: str = action.get("query") or ""

    if article_title:
        cypher: str = (
            "MATCH (a:Article {title: $title})-[:CONTAINS]->(s:Sentence) "
            "RETURN a.title AS article, s.text AS sentence "
            "LIMIT 15"
        )
        params: dict[str, str] = {"title": article_title}
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
        driver = _get_neo4j_driver()
        with driver.session() as session:
     
            result = session.run(cypher, **params)
            records: list[dict[str, Any]] = result.data()
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
