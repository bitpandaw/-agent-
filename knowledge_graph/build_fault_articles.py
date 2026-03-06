"""
从 FailureSensorIQ 构建 structured_articles.json，供 build_graph.py 导入 Neo4j。

输出结构严格保持:
  articles: [{title, sentences: [{sent_id, text}]}]
  questions: [{question_id, text, answer, ref_articles: [title, ...]}]

每个 asset 作为一个 Article，其故障模式描述作为 sentences。使用完整 8296 条。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = Path(__file__).resolve().parent / "structured_articles.json"
MAX_SAMPLES = 8296


def _build_from_seed() -> tuple[list[dict], list[dict]]:
    """从 failuresensoriq_db_seed.json 构建（HF 不可用时的后备）。"""
    seed_path: Path = Path(__file__).resolve().parents[1] / "failuresensoriq_db_seed.json"
    if not seed_path.exists():
        return [], []
    data: list[dict] = json.loads(seed_path.read_text(encoding="utf-8"))
    articles_map: dict[str, list[dict]] = {}
    questions: list[dict] = []
    for i, item in enumerate(data[:MAX_SAMPLES]):
        titles: list = item.get("article_titles", [])
        asset: str = titles[0] if titles else "Unknown"
        question: str = (item.get("question") or "").strip()
        answer: str = item.get("answer", "")
        sent_text: str = (
            f"Failure mode: {question[:300]}. Related sensors: {answer}."
        )
        if asset not in articles_map:
            articles_map[asset] = []
        articles_map[asset].append({"sent_id": len(articles_map[asset]), "text": sent_text})
        questions.append({
            "question_id": f"fsiq_{i + 1:03d}",
            "text": question,
            "answer": answer,
            "ref_articles": [asset],
        })
    articles = [{"title": t, "sentences": s} for t, s in articles_map.items()]
    return articles, questions


def main() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    articles: list[dict] = []
    questions: list[dict] = []
    try:
        from scripts.failuresensoriq_loader import (
            get_answer_text,
            load_failuresensoriq_fm2,
        )

        print("Loading FailureSensorIQ (full 8296)...")
        samples: list[dict] = load_failuresensoriq_fm2(max_samples=MAX_SAMPLES)

        articles_map: dict[str, list[dict]] = {}
        for i, row in enumerate(samples):
            asset: str = str(
                row.get("asset_name") or row.get("asset") or "Unknown"
            ).strip()
            question: str = (row.get("question") or "").strip()
            answer: str = get_answer_text(row)

            sent_text: str = (
                f"Failure mode: {question[:300]}. "
                f"Related sensors: {answer or 'N/A'}."
            )
            if asset not in articles_map:
                articles_map[asset] = []
            articles_map[asset].append({"sent_id": len(articles_map[asset]), "text": sent_text})

            questions.append({
                "question_id": f"fsiq_{i + 1:03d}",
                "text": question,
                "answer": answer,
                "ref_articles": [asset],
            })

        articles = [{"title": t, "sentences": s} for t, s in articles_map.items()]
    except Exception as e:
        print(f"HF/local load failed: {e}, using seed file.")
        articles, questions = _build_from_seed()

    if not articles:
        raise FileNotFoundError(
            "No data. Ensure failuresensoriq_db_seed.json exists or HF is accessible."
        )

    result: dict = {"articles": articles, "questions": questions}
    OUTPUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(articles)} articles, {len(questions)} questions -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
