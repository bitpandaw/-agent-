"""初始化 hotpot.db，创建 qa_records 表。

优先从 hotpotqa_db_seed.json 加载；若不存在则从 HuggingFace HotpotQA 采样。
"""

import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from config.config_loader import config

SEED_FILE = Path(__file__).resolve().parent / "hotpotqa_db_seed.json"


def _load_from_seed() -> list[tuple[str, str, str, str]] | None:
    """从 hotpotqa_db_seed.json 加载，返回 (question, answer, article_titles_json, created_at) 列表。"""
    if not SEED_FILE.exists():
        return None
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    records = []
    for item in data:
        q = item.get("question", "")
        a = item.get("answer", "")
        titles = item.get("article_titles", [])
        created = item.get("created_at", "")
        if q and a:
            records.append((q, a, json.dumps(titles, ensure_ascii=False), created))
    return records if records else None


def _load_from_hotpotqa() -> list[tuple[str, str, str, str]]:
    """从 HuggingFace HotpotQA 采样。"""
    from datasets import load_dataset  # noqa: PLC0415

    ds = load_dataset("hotpot_qa", "distractor", split="validation", trust_remote_code=False)
    rng = random.Random(42)
    n = min(100, len(ds))
    indices = rng.sample(range(len(ds)), n)
    base_date = datetime.now()
    records = []
    for i in indices:
        sample = ds[i]
        titles = sample["supporting_facts"]["title"]
        days_ago = random.randint(0, 90)
        created_at = (base_date - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        records.append((
            sample["question"],
            sample["answer"],
            json.dumps(titles, ensure_ascii=False),
            created_at,
        ))
    return records


def init_database() -> None:
    """创建 qa_records 表并插入数据。"""
    records = _load_from_seed()
    if records is None:
        try:
            records = _load_from_hotpotqa()
        except ImportError:
            print("Error: datasets 未安装，且 hotpotqa_db_seed.json 不存在。请 pip install datasets")
            return
        print("从 HuggingFace HotpotQA 加载...")
    else:
        print(f"从 {SEED_FILE.name} 加载...")

    db_path = config["paths"]["db"]
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qa_records (
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
        print(f"数据库初始化完成，共 {cursor.fetchone()[0]} 条 qa_records")


if __name__ == "__main__":
    init_database()
