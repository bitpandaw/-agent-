"""KG 检索模块：按实体/关键词从 Neo4j 图谱检索文档，独立于 RAG。"""

from typing import Any

from config.config_loader import config
from knowledge_graph.kg_retriever import extract_entities, fetch_docs


def retrieve_kg(
    query_en: str,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """从知识图谱按实体检索文档，返回与 RAG 兼容的 [{text, doc_id, source, hop}, ...]。

    :param query: 用户原始 query。
    :param top_k: 最多返回文档数。
    :param query_en: 若已翻译为英文，传入以复用；否则用 query。
    :return: 文档列表，每项含 text, doc_id, source, hop。
    """
    kg_cfg: dict[str, Any] = config.get("kg", {}) or {}
    max_entities: int = int(kg_cfg.get("max_entities", 6))
    max_keywords: int = int(kg_cfg.get("max_keywords", 6))
    terms: list[str] = extract_entities(
        query_en ,
        max_entities,
        max_keywords,
    )
    docs: list[dict[str, Any]] = fetch_docs(terms, kg_cfg)
    return docs[:top_k]
