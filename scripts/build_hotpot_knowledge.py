"""
从 HotpotQA distractor 构建 RAG 知识库文件。

将 context 中的 (title, sentences) 去重后按 "Title: {title}\n\n{paragraph}" 格式
拼接，按空行分块写入 data/hotpot_knowledge.txt。

用法: python scripts/build_hotpot_knowledge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = PROJECT_ROOT / "data" / "hotpot_knowledge.txt"
MAX_SAMPLES = 300  # 控制规模，取前 N 条样本的 context 去重


def extract_chunks_from_sample(sample: dict) -> list[tuple[str, str]]:
    """从单条 HotpotQA 样本提取 (title, paragraph) 列表。"""
    ctx_titles = sample["context"]["title"]
    ctx_sentences = sample["context"]["sentences"]
    chunks: list[tuple[str, str]] = []
    for title, sents in zip(ctx_titles, ctx_sentences):
        if not title or not sents:
            continue
        paragraph = " ".join(str(s).strip() for s in sents if s)
        if paragraph:
            chunks.append((title, paragraph))
    return chunks


def main() -> None:
    try:
        from datasets import load_dataset
    except ImportError:
        print("Error: datasets 未安装。请运行: pip install datasets")
        sys.exit(1)

    print("加载 HotpotQA distractor (train + validation)...")
    train_ds = load_dataset("hotpot_qa", "distractor", split="train", trust_remote_code=False)
    val_ds = load_dataset("hotpot_qa", "distractor", split="validation", trust_remote_code=False)

    seen_titles: set[str] = set()
    all_chunks: list[str] = []

    def add_from_split(ds, n: int) -> None:
        for i in range(min(n, len(ds))):
            sample = ds[i]
            for title, para in extract_chunks_from_sample(sample):
                if title not in seen_titles:
                    seen_titles.add(title)
                    all_chunks.append(f"Title: {title}\n\n{para}")

    n_per_split = MAX_SAMPLES // 2
    add_from_split(train_ds, n_per_split)
    add_from_split(val_ds, n_per_split)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = "\n\n".join(all_chunks)
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    print(f"完成: 共 {len(all_chunks)} 个文本块，已写入 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
