#!/usr/bin/env python3
"""
生成 RAG 检索评估的手工校验对比报告。
运行方式：在项目根目录执行 python experiments/gen_verification_report.py
"""
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
import sys
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import chromadb
from config.config_loader import config
from tools.tool_registry import get_embedding_model
from rag.rag_pipeline import (
    load_and_chunk_document,
    index_documents,
    retrieve_context,
)

EXPECTED_TRUNCATE = 800
PREVIEW_LEN = 200


def load_test_cases():
    path = Path(__file__).parent / "test_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["categories"]["rag_retrieval"]["cases"]


def doc_id_to_index(doc_id: str) -> int:
    """doc_4 -> 4"""
    return int(doc_id.replace("doc_", ""))


def main():
    knowledge_path = project_root / config["paths"]["knowledge_file"]
    chunks = load_and_chunk_document(str(knowledge_path))

    chroma_client = chromadb.Client()
    distance = config["rag"].get("distance", "l2")
    collection = chroma_client.get_or_create_collection(
        name="rag_verification",
        metadata={"hnsw:space": distance},
    )
    embedding_model = get_embedding_model()
    context = {
        "embedding_model": embedding_model,
        "collection": collection,
        "config": config,
    }
    index_documents(chunks, context)

    rag_config = config["rag"]
    top_k = rag_config["top_k"]
    score_threshold = rag_config["score_threshold"]

    cases = load_test_cases()
    lines = []

    for case in cases:
        case_id = case["id"]
        query = case["query"]
        expected_doc_id = case["expected_doc_id"]

        # expected_doc 内容
        try:
            idx = doc_id_to_index(expected_doc_id)
            expected_text = chunks[idx] if 0 <= idx < len(chunks) else "(索引超出范围)"
        except (ValueError, IndexError):
            expected_text = "(无法解析 expected_doc_id)"
        expected_preview = expected_text[:EXPECTED_TRUNCATE]
        if len(expected_text) > EXPECTED_TRUNCATE:
            expected_preview += "..."

        # 实际检索结果
        ret = retrieve_context(query, context, top_k, score_threshold)

        block = []
        block.append("=" * 60)
        block.append(f"【Case: {case_id}】")
        block.append(f"query: {query}")
        block.append(f"expected_doc_id: {expected_doc_id}")
        block.append("--- expected_doc 内容（来自 chunks[" + str(doc_id_to_index(expected_doc_id)) + "]）---")
        block.append(expected_preview)
        block.append("--- end expected_doc ---")
        block.append("")
        block.append("--- 实际检索 top_k 结果 ---")
        for r in ret:
            doc_id = r.get("doc_id", "?")
            text = r.get("text", "")
            preview = text[:PREVIEW_LEN] + ("..." if len(text) > PREVIEW_LEN else "")
            block.append(f"{doc_id}  | {preview.replace(chr(10), ' ')}")
        block.append("--- end 实际检索 ---")
        block.append("")
        block.append("[ ] 手工勾选：expected 是否应为此 query 的正确答案？")
        block.append("[ ] 手工勾选：实际检索是否命中了 expected？")
        block.append("=" * 60)
        lines.append("\n".join(block))

    out_path = Path(__file__).parent / "verification_report.txt"
    content = "\n\n".join(lines)
    out_path.write_text(content, encoding="utf-8")
    print(f"报告已生成: {out_path}")


if __name__ == "__main__":
    main()
