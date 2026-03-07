"""验证 _fetch_kg 使用 CONTAINS 对 HotpotQA 问句的命中情况。"""

import sys
from pathlib import Path

from neo4j import GraphDatabase

ROOT: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.config_loader import config

CYPHER: str = (
    "MATCH (a:Article)-[:CONTAINS]->(s:Sentence) "
    "WHERE s.text CONTAINS $query OR a.title CONTAINS $query "
    "RETURN a.title AS article, s.text AS sentence LIMIT 15"
)

SAMPLES: list[str] = [
    "In what year was Moscow State University founded?",
    "Who wrote the song that was covered by the band that had a member who played "
    "in the film directed by Stanley Kubrick?",
    "Moscow State University",
    "Moscow",
]


if __name__ == "__main__":
    cfg = config["neo4j"]
    driver = GraphDatabase.driver(
        cfg["uri"], auth=(cfg["user"], cfg["password"])
    )

    # 1. Sample graph content
    with driver.session() as session:
        sample = session.run(
            "MATCH (a:Article)-[:CONTAINS]->(s:Sentence) "
            "RETURN a.title, s.text LIMIT 3"
        ).data()
    print("=== Sample KG content ===")
    for r in sample:
        print("  ", r["a.title"], ":", str(r["s.text"])[:80])

    print("\n=== CONTAINS test ===")
    for q in SAMPLES:
        with driver.session() as session:
            recs = session.run(CYPHER, {"query": q}).data()
        qs = q[:60] + "..." if len(q) > 60 else q
        print("Query:", qs)
        print("  KG results:", len(recs))
        if recs:
            for r in recs[:2]:
                s = str(r["sentence"])[:80]
                print("    ->", r["article"], ":", s)
    driver.close()
    print("\nDone.")
