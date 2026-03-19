"""从 structured_articles.json 导入 Neo4j 知识图谱（LightRAG 风格）。

保留：
- (:Article {title})
- (:Sentence {text})
- (:Article)-[:CONTAINS]->(:Sentence)

替换/新增：
- (:Entity {name, type})
- (:Sentence)-[:MENTIONS]->(:Entity)
- (:Entity)-[:RELATED {keywords, desc}]->(:Entity)

实体与关系通过 DeepSeek LLM 从句子级文本中抽取。

需先运行 build_hotpot_articles.py 生成 structured_articles.json。

用法: python knowledge_graph/build_graph.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import OpenAI
from config.config_loader import config

INPUT_FILE = Path(__file__).resolve().parent / "structured_articles.json"


# LLM 提示模板
SYSTEM_PROMPT: str = (
    "你是一个信息抽取助手。从文本中抽取实体和关系，严格按格式输出，不要有任何多余内容。"
)

USER_TEMPLATE: str = (
    "从以下文本中抽取实体和关系。\n\n"
    "输出格式：\n"
    "entity|实体名|实体类型|描述\n"
    "relation|源实体|目标实体|关系关键词|关系描述\n\n"
    "实体类型只能是：PERSON, ORG, LOCATION, EVENT, CONCEPT, OTHER\n"
    "每行一条，无其他内容。\n\n"
    "文本：{sentence_text}"
)

_llm_client: Optional[OpenAI] = None


def _get_llm_client() -> Optional[OpenAI]:
    """懒加载 DeepSeek（OpenAI 兼容）客户端。"""
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    llm_cfg: Dict[str, Any] = config["llm"]
    api_key_env: str = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
    api_key: str = os.environ.get(api_key_env, "")
    if not api_key:
        print(f"Warning: {api_key_env} 未设置，LLM 实体抽取将被跳过。")
        _llm_client = None
        return None

    _llm_client = OpenAI(
        api_key=api_key,
        base_url=llm_cfg.get("base_url"),
    )
    return _llm_client


def _parse_llm_output(
    raw: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """解析 LLM 输出为实体与关系列表。

    实体: {"name", "type", "desc}
    关系: {"source", "target", "keywords", "desc"}
    """
    entities: List[Dict[str, str]] = []
    relations: List[Dict[str, str]] = []

    if not raw:
        return entities, relations

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts: List[str] = [p.strip() for p in line.split("|")]
        if not parts:
            continue

        tag = parts[0].lower()
        if tag == "entity" and len(parts) >= 4:
            name, etype, desc = parts[1], parts[2], parts[3]
            if name:
                entities.append(
                    {"name": name, "type": etype or "OTHER", "desc": desc or ""}
                )
        elif tag == "relation" and len(parts) >= 5:
            source, target, keywords, desc = parts[1], parts[2], parts[3], parts[4]
            if source and target:
                relations.append(
                    {
                        "source": source,
                        "target": target,
                        "keywords": keywords or "",
                        "desc": desc or "",
                    }
                )

    return entities, relations


def _extract_with_llm(
    text: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """调用 LLM 从单句文本中抽取实体与关系。

    调用失败时抛出异常，由上层捕获并跳过该句。
    """
    client = _get_llm_client()
    if client is None:
        return [], []

    llm_cfg: Dict[str, Any] = config["llm"]
    user_content: str = USER_TEMPLATE.format(sentence_text=text)

    response: Any = client.chat.completions.create(
        model=llm_cfg["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
    )
    content: str = response.choices[0].message.content or ""
    return _parse_llm_output(content)


def main() -> None:
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} 不存在。请先运行 build_hotpot_articles.py")
        sys.exit(1)

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

    print(
        f"创建 {len(articles)} 篇文章、Sentence、Entity、MENTIONS、RELATED 边（LLM 抽取）..."
    )
    with driver.session() as session:
        for idx, art in enumerate(articles):
            title = art.get("title", "").strip()
            if not title:
                continue
            session.execute_write(
                lambda tx: tx.run("MERGE (a:Article {title: $title})", {"title": title})
            )
            # 同一文章内的实体去重：按 name 聚合
            article_entities: Dict[str, Dict[str, str]] = {}
            mentions: List[Tuple[str, str]] = []  # (sentence_text, entity_name)
            relations: List[Dict[str, str]] = []

            for sent in art.get("sentences", []):
                text = (sent.get("text") or "").strip()
                if not text:
                    continue

                # 先写入 Sentence 节点及 CONTAINS 关系
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

                # 用 LLM 抽取实体与关系；失败时跳过该句
                try:
                    ents, rels = _extract_with_llm(text)
                except Exception as e:  # noqa: PERF203
                    print(f"[WARN] LLM 调用失败，跳过句子: {e}")
                    continue

                for ent in ents:
                    name = (ent.get("name") or "").strip()
                    if not name:
                        continue
                    if name not in article_entities:
                        article_entities[name] = {
                            "name": name,
                            "type": ent.get("type") or "OTHER",
                            "desc": ent.get("desc") or "",
                        }
                    mentions.append((text, name))

                for rel in rels:
                    src = (rel.get("source") or "").strip()
                    tgt = (rel.get("target") or "").strip()
                    if not src or not tgt:
                        continue
                    relations.append(
                        {
                            "source": src,
                            "target": tgt,
                            "keywords": rel.get("keywords") or "",
                            "desc": rel.get("desc") or "",
                        }
                    )

            # 将去重后的实体写入 Neo4j，并建立 MENTIONS 与 RELATED 关系
            def _write_entities_and_relations(
                tx: Any,
                ents: Dict[str, Dict[str, str]],
                ments: List[Tuple[str, str]],
                rels: List[Dict[str, str]],
            ) -> None:
                for ent in ents.values():
                    tx.run(
                        """
                        MERGE (e:Entity {name: $name})
                        SET e.type = $type, e.desc = $desc
                        """,
                        {
                            "name": ent["name"],
                            "type": ent.get("type", "OTHER"),
                            "desc": ent.get("desc", ""),
                        },
                    )

                for sent_text, ent_name in ments:
                    tx.run(
                        """
                        MATCH (s:Sentence {text: $text})
                        MATCH (e:Entity {name: $name})
                        MERGE (s)-[:MENTIONS]->(e)
                        """,
                        {"text": sent_text, "name": ent_name},
                    )

                for rel in rels:
                    tx.run(
                        """
                        MERGE (e1:Entity {name: $src})
                        MERGE (e2:Entity {name: $tgt})
                        MERGE (e1)-[r:RELATED]->(e2)
                        ON CREATE SET r.keywords = $keywords, r.desc = $desc
                        """,
                        {
                            "src": rel["source"],
                            "tgt": rel["target"],
                            "keywords": rel.get("keywords", ""),
                            "desc": rel.get("desc", ""),
                        },
                    )

            if article_entities or mentions or relations:
                session.execute_write(
                    _write_entities_and_relations,
                    article_entities,
                    mentions,
                    relations,
                )

            if (idx + 1) % 100 == 0:
                print(f"  已处理 {idx + 1}/{len(articles)} 篇文章...")

    driver.close()
    print(f"完成: {len(articles)} 篇文章的图谱构建（LLM 实体与关系）。")


if __name__ == "__main__":
    main()
