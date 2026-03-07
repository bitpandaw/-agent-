"""从 HotpotQA validation 生成 hotpot.db，供 query_qa_records 工具使用。

不依赖 hotpotqa_db_seed.json，确保数据来源于 HuggingFace HotpotQA。

用法: python scripts/build_hotpot_db.py
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.config_loader import config

def main() -> None:
    try:
        from datasets import load_dataset
    except ImportError:
        print("Error: pip install datasets")
        sys.exit(1)

    print("加载 HotpotQA distractor validation（全部）...")
    ds: Any = load_dataset(
        "hotpot_qa", "distractor", split="validation", trust_remote_code=False
    )

    indices = list(range(len(ds)))
    base_date = datetime.now()

    records: list[tuple[str, str, str, str]] = []
    for i in indices:
        sample = ds[i]
        titles = sample["supporting_facts"]["title"]
        days_ago = random.randint(0, 90)
        created_at = (base_date - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        answer = sample["answer"]
        if isinstance(answer, list):
            answer = answer[0] if answer else ""
        records.append((
            sample["question"],
            str(answer).strip(),
            json.dumps(titles, ensure_ascii=False),
            created_at,
        ))

    db_path = config["paths"]["db"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS qa_records")
    cursor.execute("""
        CREATE TABLE qa_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            article_titles TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.executemany(
        "INSERT INTO qa_records(question, answer, article_titles, created_at) VALUES(?,?,?,?)",
        records,
    )
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM qa_records")
    count = cursor.fetchone()[0]
    conn.close()

    print(f"完成: {count} 条 qa_records -> {db_path}")


if __name__ == "__main__":
    main()
