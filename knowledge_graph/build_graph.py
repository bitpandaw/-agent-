"""从 structured_articles.json 导入 Neo4j，构建 HotpotQA 知识图谱。

节点：Article, Sentence, Question, Entity
关系：CONTAINS, REFERENCES, CO_OCCURS_WITH, MENTIONS

用法：
  1. pip install spacy && python -m spacy download en_core_web_sm
  2. python knowledge_graph/build_hotpot_articles.py  # 生成 structured_articles.json
  3. 确保 Neo4j 已启动
  4. python knowledge_graph/build_graph.py
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import spacy
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "u152142445")

# spaCy 模型，main 中加载
_nlp: Optional[Any] = None

# 保留的实体类型（PERSON/ORG/GPE/LOC/FAC 等对多跳推理有用）
ENTITY_TYPES = frozenset({"PERSON", "ORG", "GPE", "LOC", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART"})


def extract_entities(text: str) -> List[Tuple[str, str]]:
    """用 spaCy NER 抽取实体，返回 [(name, type), ...]，过滤无关类型。"""
    if _nlp is None:
        return []
    doc: Any = _nlp(text)
    out: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for ent in doc.ents:
        if ent.label_ not in ENTITY_TYPES:
            continue
        name: str = ent.text.strip()
        if len(name) > 200:
            name = name[:200]
        key: Tuple[str, str] = (name, ent.label_)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def clear_graph(tx: Any) -> None:
    tx.run("MATCH (n) DETACH DELETE n")


def create_constraints(tx: Any) -> None:
    for c in [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Article) REQUIRE a.title IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (q:Question) REQUIRE q.question_id IS UNIQUE",
        "CREATE CONSTRAINT entity_name_type IF NOT EXISTS FOR (e:Entity) "
        "REQUIRE (e.name, e.type) IS UNIQUE",
    ]:
        try:
            tx.run(c)
        except Exception:
            # Neo4j 旧版本可能不支持复合约束，忽略
            pass


def import_article(tx: Any, article: Dict[str, Any]) -> None:
    title: str = article.get("title", "")
    if not title:
        return
    tx.run("MERGE (a:Article {title: $title})", title=title)
    for sent in article.get("sentences", []):
        text: str = sent.get("text", "").strip()
        sent_id: int = sent.get("sent_id", 0)
        if not text:
            continue
        tx.run(
            """
            MATCH (a:Article {title: $title})
            CREATE (s:Sentence {sent_id: $sent_id, text: $text})
            MERGE (a)-[:CONTAINS]->(s)
            """,
            title=title,
            sent_id=sent_id,
            text=text[:500],
        )
        entities: List[Tuple[str, str]] = extract_entities(text)
        for name, etype in entities:
            tx.run(
                """
                MERGE (e:Entity {name: $name, type: $type})
                WITH e
                MATCH (a:Article {title: $title})-[:CONTAINS]->(s:Sentence {sent_id: $sent_id})
                MERGE (s)-[:MENTIONS]->(e)
                """,
                name=name,
                type=etype,
                title=title,
                sent_id=sent_id,
            )


def import_question(tx: Any, q: Dict[str, Any]) -> None:
    qid: str = q.get("question_id", "")
    text: str = q.get("text", "")
    answer: str = q.get("answer", "")
    ref_articles: List[str] = q.get("ref_articles", [])
    if not qid:
        return
    tx.run(
        "MERGE (q:Question {question_id: $qid}) SET q.text = $text, q.answer = $answer",
        qid=qid,
        text=text[:1000],
        answer=answer[:200],
    )
    for t in ref_articles:
        tx.run(
            """
            MATCH (q:Question {question_id: $qid})
            MATCH (a:Article {title: $title})
            MERGE (q)-[:REFERENCES]->(a)
            """,
            qid=qid,
            title=t,
        )


def create_co_occurs(tx: Any, questions: List[Dict[str, Any]]) -> None:
    """同一问题的多篇文章建立 CO_OCCURS_WITH。"""
    for q in questions:
        refs: List[str] = q.get("ref_articles", [])
        for i, t1 in enumerate(refs):
            for t2 in refs[i + 1 :]:
                tx.run(
                    """
                    MATCH (a1:Article {title: $t1})
                    MATCH (a2:Article {title: $t2})
                    MERGE (a1)-[:CO_OCCURS_WITH]->(a2)
                    """,
                    t1=t1,
                    t2=t2,
                )


def print_stats(session: Any) -> None:
    r: Any = session.run(
        "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC"
    )
    print("\n--- Graph Statistics ---")
    for rec in r:
        print(f"  {rec['label']}: {rec['cnt']}")
    r = session.run(
        "MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC"
    )
    for rec in r:
        print(f"  {rec['rel']}: {rec['cnt']}")


def main() -> None:
    global _nlp
    try:
        _nlp = spacy.load("en_core_web_sm")
        print("Loaded spaCy model en_core_web_sm for NER.")
    except OSError:
        print(
            "Warning: en_core_web_sm not found. Run: python -m spacy download en_core_web_sm"
        )
        print("Proceeding without Entity extraction.")
        _nlp = None

    base_dir: Path = Path(__file__).resolve().parent
    input_path: Path = base_dir / "structured_articles.json"
    if not input_path.exists():
        print("Error: structured_articles.json not found. Run build_hotpot_articles.py first.")
        return

    data: Dict[str, Any] = json.loads(
        input_path.read_text(encoding="utf-8")
    )
    articles: List[Dict[str, Any]] = data.get("articles", [])
    questions: List[Dict[str, Any]] = data.get("questions", [])

    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    driver: Any = GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"Error: Cannot connect to Neo4j: {e}")
        return

    with driver.session() as session:
        session.execute_write(clear_graph)
        session.execute_write(create_constraints)
        print(f"Importing {len(articles)} articles...")
        for i, a in enumerate(articles):
            session.execute_write(import_article, a)
            if (i + 1) % 100 == 0:
                print(f"  [{i + 1}/{len(articles)}]")
        print(f"Importing {len(questions)} questions...")
        for q in questions:
            session.execute_write(import_question, q)
        print("Creating CO_OCCURS_WITH...")
        session.execute_write(create_co_occurs, questions)
        print_stats(session)

    driver.close()
    print("\nDone. Open http://localhost:7474 to explore.")


if __name__ == "__main__":
    main()
