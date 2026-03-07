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


def _strip_leading_stopwords(phrase: str) -> str:
    """去掉短语开头的 stopword，避免 'Were Scott Derrickson' 无法匹配 'scott derrickson'。"""
    words = phrase.strip().split()
    while words and words[0].lower() in _STOPWORDS:
        words.pop(0)
    return " ".join(words).strip()


def extract_entities(query: str, max_entities: int, max_keywords: int) -> list[str]:
    """从 query 抽取实体/关键词，用于 KG 检索。返回小写列表以匹配 toLower(e.name)。
    优先多词实体，单 token 仅作补充以减少噪声。
    """
    if not query:
        return []

    phrases = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
    quoted = [p[0] or p[1] for p in phrases if (p[0] or p[1])]
    caps = re.findall(r"\b(?:[A-Z][a-z]+(?:\s+|$)){1,5}", query)
    caps = [_strip_leading_stopwords(c.strip()) for c in caps if c.strip()]
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]+", query)
    tokens = [t for t in tokens if t.lower() not in _STOPWORDS]
    tokens = sorted(tokens, key=len, reverse=True)

    # 优先多词实体：quoted + caps（已去句首 stopword）
    multi_word: list[str] = []
    for item in quoted + caps:
        if not item or item.lower() in _STOPWORDS:
            continue
        key = item.strip().lower()
        if key and key not in multi_word:
            multi_word.append(key)

    # 若多词短语为单个词，也视为多词优先级（如 "Animorphs"）
    seen: set[str] = set(multi_word)
    entities: list[str] = list(multi_word)

    # 单 token 仅作补充：排除已是多词实体子词的 token（避免 scott/wood 单独命中噪声）
    def _is_subword(tok: str, phrases: list[str]) -> bool:
        tok_lower = tok.lower()
        for p in phrases:
            words = p.split()
            if tok_lower in (w.lower() for w in words):
                return True
        return False

    for t in tokens:
        if len(entities) >= max_entities + max_keywords:
            break
        key = t.lower()
        if key in seen or _is_subword(key, multi_word) or len(key) < 3:
            continue
        seen.add(key)
        entities.append(key)

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

    # 精确匹配 + 多词 term 的 CONTAINS（如 "ed wood" 匹配 "ed wood (film)"）
    multi_terms = [t for t in terms if " " in t]

    cypher_h1 = (
        "MATCH (e:Entity)<-[:MENTIONS]-(s:Sentence)<-[:CONTAINS]-(a:Article) "
        "WHERE toLower(e.name) IN $terms "
        "OR (size($multiTerms) > 0 AND "
        "ANY(t IN $multiTerms WHERE toLower(e.name) CONTAINS t)) "
        "RETURN e.name AS entity, s.text AS s1, a.title AS a1 "
        "LIMIT $limit"
    )
    cypher_h2 = (
        "MATCH (e:Entity)<-[:MENTIONS]-(s1:Sentence)<-[:CONTAINS]-(a1:Article) "
        "WHERE toLower(e.name) IN $terms "
        "OR (size($multiTerms) > 0 AND "
        "ANY(t IN $multiTerms WHERE toLower(e.name) CONTAINS t)) "
        "MATCH (a1)-[:CO_OCCURS_WITH]->(a2:Article) "
        "MATCH (a2)-[:CONTAINS]->(s2:Sentence) "
        "RETURN a1.title AS a1, s1.text AS s1, a2.title AS a2, s2.text AS s2 "
        "LIMIT $limit"
    )

    params = {"terms": terms, "multiTerms": multi_terms if multi_terms else [], "limit": hop1_limit}
    params_h2 = {"terms": terms, "multiTerms": multi_terms if multi_terms else [], "limit": hop2_limit}
    try:
        with driver.session() as session:
            recs_h1 = session.run(cypher_h1, params).data()
            recs_h2 = (
                session.run(cypher_h2, params_h2).data() if use_hop2 else []
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

