"""知识图谱检索模块：从 Neo4j 提取实体和文档。"""

import re
from typing import Any

from config.config_loader import config


_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "when",
    "where",
    "who",
    "whom",
    "whose",
    "which",
    "what",
    "why",
    "how",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "with",
    "without",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "to",
    "from",
    "as",
    "about",
    "into",
    "over",
    "after",
    "before",
    "between",
}


def extract_entities(query: str, max_entities: int, max_keywords: int) -> list[str]:
    """从 query 抽取实体/关键词，用于 KG 检索。返回小写列表以匹配 toLower(e.name)。"""
    if not query:
        return []

    phrases = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
    quoted = [p[0] or p[1] for p in phrases if (p[0] or p[1])]
    caps = re.findall(r"\\b(?:[A-Z][a-z]+(?:\\s+|$)){1,5}", query)
    caps = [c.strip() for c in caps if c.strip()]
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\\-']+", query)
    tokens = [t for t in tokens if t.lower() not in _STOPWORDS]
    tokens = sorted(tokens, key=len, reverse=True)

    out: list[str] = []
    for item in quoted + caps:
        if item and item.lower() not in _STOPWORDS:
            out.append(item.strip())
    for t in tokens:
        out.append(t)

    seen: set[str] = set()
    entities: list[str] = []
    for x in out:
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(key)
        if len(entities) >= max_entities:
            break

    if len(entities) < max_entities:
        for t in tokens:
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            entities.append(key)
            if len(entities) >= max_entities + max_keywords:
                break

    return entities[: max_entities + max_keywords]


def fetch_docs(terms: list[str], kg_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """从 Neo4j KG 按实体 1–2 跳检索，返回 [{text, doc_id, source, hop}, ...]。"""
    try:
        from neo4j import GraphDatabase
    except Exception:
        return []

    if not terms:
        return []

    cfg = config["neo4j"]
    driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))

    hop1_limit = int(kg_cfg.get("hop1_limit", 30))
    hop2_limit = int(kg_cfg.get("hop2_limit", 40))
    chain_limit = int(kg_cfg.get("chain_limit", 40))
    chain_sep = kg_cfg.get("chain_sep", " [SEP] ")
    use_hop2 = bool(kg_cfg.get("use_hop2", True))

    cypher_h1 = (
        "MATCH (e:Entity) "
        "WHERE toLower(e.name) IN $terms "
        "MATCH (e)<-[:MENTIONS]-(s:Sentence)<-[:CONTAINS]-(a:Article) "
        "RETURN e.name AS entity, s.text AS s1, a.title AS a1 "
        "LIMIT $limit"
    )
    cypher_h2 = (
        "MATCH (e:Entity) "
        "WHERE toLower(e.name) IN $terms "
        "MATCH (e)<-[:MENTIONS]-(s1:Sentence)<-[:CONTAINS]-(a1:Article) "
        "MATCH (a1)-[:CO_OCCURS_WITH]->(a2:Article) "
        "MATCH (a2)-[:CONTAINS]->(s2:Sentence) "
        "RETURN a1.title AS a1, s1.text AS s1, a2.title AS a2, s2.text AS s2 "
        "LIMIT $limit"
    )

    try:
        with driver.session() as session:
            recs_h1 = session.run(
                cypher_h1, {"terms": terms, "limit": hop1_limit}
            ).data()
            recs_h2 = (
                session.run(
                    cypher_h2, {"terms": terms, "limit": hop2_limit}
                ).data()
                if use_hop2
                else []
            )
    finally:
        driver.close()

    docs: list[dict[str, Any]] = []
    for r in recs_h1:
        s1 = (r.get("s1") or "").strip()
        a1 = (r.get("a1") or "").strip()
        if not s1:
            continue
        docs.append(
            {
                "text": s1,
                "doc_id": f"kg1_{a1}",
                "source": "kg",
                "hop": 1,
            }
        )

    chain_count = 0
    for r in recs_h2:
        if chain_count >= chain_limit:
            break
        s1 = (r.get("s1") or "").strip()
        s2 = (r.get("s2") or "").strip()
        a1 = (r.get("a1") or "").strip()
        a2 = (r.get("a2") or "").strip()
        if not s1 or not s2 or not a1 or not a2:
            continue
        text = f"{s1}{chain_sep}{s2}"
        docs.append(
            {
                "text": text,
                "doc_id": f"kg2_{a1}__{a2}",
                "source": "kg",
                "hop": 2,
            }
        )
        chain_count += 1

    return docs

