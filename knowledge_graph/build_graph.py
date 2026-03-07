"""从 structured_articles.json 导入 Neo4j 知识图谱。

创建 Article、Sentence、Entity 节点及 CONTAINS、MENTIONS、CO_OCCURS_WITH 边。
需先运行 build_hotpot_articles.py 生成 structured_articles.json。

用法: python knowledge_graph/build_graph.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INPUT_FILE = Path(__file__).resolve().parent / "structured_articles.json"


_nlp: Any = None


def _get_nlp() -> Any:
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except (ImportError, OSError):
            _nlp = False
    return _nlp if _nlp else None


def _extract_entities_spacy(text: str) -> list[str]:
    """用 spaCy 抽取命名实体，返回去重的小写列表。"""
    nlp = _get_nlp()
    if nlp is None:
        return []
    doc = nlp(text)
    seen: set[str] = set()
    out: list[str] = []
    for ent in doc.ents:
        name = (ent.text or "").strip().lower()
        if name and len(name) > 1 and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def main() -> None:
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} 不存在。请先运行 build_hotpot_articles.py")
        sys.exit(1)

    from config.config_loader import config

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: pip install neo4j")
        sys.exit(1)

    data = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    articles: list[dict] = data.get("articles", [])
    questions: list[dict] = data.get("questions", [])

    cfg = config["neo4j"]
    driver = GraphDatabase.driver(
        cfg["uri"], auth=(cfg["user"], cfg["password"])
    )

    print("清空现有图数据...")
    with driver.session() as session:
        session.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))

    print(f"创建 {len(articles)} 篇文章、Sentence、Entity 及 CO_OCCURS_WITH...")
    with driver.session() as session:
        for idx, art in enumerate(articles):
            title = art.get("title", "").strip()
            if not title:
                continue
            session.execute_write(
                lambda tx: tx.run("MERGE (a:Article {title: $title})", {"title": title})
            )
            for sent in art.get("sentences", []):
                text = (sent.get("text") or "").strip()
                if not text:
                    continue
                session.execute_write(
                    lambda tx, t=title, txt=text: tx.run(
                        """
                        MATCH (a:Article {title: $title})
                        MERGE (s:Sentence {text: $text})
                        MERGE (a)-[:CONTAINS]->(s)
                        """,
                        {"title": t, "text": txt},
                    )
                )
                entities = _extract_entities_spacy(text)
                for ent_name in entities:
                    session.execute_write(
                        lambda tx, n=ent_name, txt=text: tx.run(
                            """
                            MERGE (e:Entity {name: $name})
                            WITH e
                            MATCH (s:Sentence {text: $text})
                            MERGE (s)-[:MENTIONS]->(e)
                            """,
                            {"name": n, "text": txt},
                        )
                    )
            if (idx + 1) % 1000 == 0:
                print(f"  已处理 {idx + 1}/{len(articles)} 篇文章...")

    print("创建 CO_OCCURS_WITH 边...")
    co_occurs: set[tuple[str, str]] = set()
    for q in questions:
        titles = q.get("context_titles") or q.get("ref_articles") or []
        titles = [t.strip() for t in titles if t and isinstance(t, str)]
        for i in range(len(titles)):
            for j in range(i + 1, len(titles)):
                a, b = titles[i], titles[j]
                if a != b:
                    co_occurs.add((min(a, b), max(a, b)))
    co_list = list(co_occurs)
    with driver.session() as session:
        for i, (a1, a2) in enumerate(co_list):
            session.execute_write(
                lambda tx, x=a1, y=a2: tx.run(
                    """
                    MATCH (a1:Article {title: $a1}), (a2:Article {title: $a2})
                    WHERE a1 <> a2
                    MERGE (a1)-[:CO_OCCURS_WITH]->(a2)
                    """,
                    {"a1": x, "a2": y},
                )
            )
            if (i + 1) % 5000 == 0:
                print(f"  已创建 {i + 1}/{len(co_list)} 条 CO_OCCURS_WITH 边...")
    driver.close()
    print(f"完成: {len(articles)} 篇文章, {len(co_occurs)} 条 CO_OCCURS_WITH 边")


if __name__ == "__main__":
    main()
