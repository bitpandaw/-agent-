"""从 HotpotQA 构建 structured_articles.json，供 build_graph.py 导入 Neo4j。

输出结构:
  - articles: [{title, sentences: [{sent_id, text}]}]
  - questions: [{question_id, text, answer, ref_articles: [title, ...]}]

用法: python knowledge_graph/build_hotpot_articles.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

OUTPUT_FILE = Path(__file__).resolve().parent / "structured_articles.json"



def main() -> None:
    try:
        from datasets import load_dataset
    except ImportError:
        print("Error: pip install datasets")
        sys.exit(1)

    print("加载 HotpotQA distractor validation（全量）...")
    ds: Any = load_dataset(
        "hotpot_qa", "distractor", split="validation", trust_remote_code=False
    )

    articles_map: dict[str, list[dict[str, Any]]] = {}
    questions: list[dict[str, Any]] = []

    for i in range(len(ds)):
        sample: dict = ds[i]
        ctx_titles: list = sample["context"]["title"]
        ctx_sentences: list = sample["context"]["sentences"]
        sf_titles: list = sample["supporting_facts"]["title"]

        for title, sents in zip(ctx_titles, ctx_sentences):
            if title not in articles_map:
                articles_map[title] = [
                    {"sent_id": j, "text": str(s).strip()}
                    for j, s in enumerate(sents) if s
                ]

        questions.append({
            "question_id": f"q{i}",
            "text": sample["question"],
            "answer": sample["answer"],
            "ref_articles": list(dict.fromkeys(sf_titles)),
            "context_titles": list(ctx_titles),
        })
        if (i + 1) % 1000 == 0:
            print(f"  已处理 {i + 1}/{len(ds)} 样本...")

    result: dict[str, Any] = {
        "articles": [{"title": t, "sentences": s} for t, s in articles_map.items()],
        "questions": questions,
    }
    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成: {len(articles_map)} 篇文章, {len(questions)} 个问题 -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
