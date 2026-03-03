#!/usr/bin/env python3
"""
RAG 归一化对比实验：有归一化 vs 无归一化
运行方式：在项目根目录执行 python experiments/run_rag_norm_experiment.py
"""
import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import chromadb
from config.config_loader import config
from tools.tool_registry import get_embedding_model
from rag.rag_pipeline import (
    load_and_chunk_document,
    index_documents,
    retrieve_context,
    retrieve_context_raw,
)


def load_test_cases():
    path = Path(__file__).parent / "test_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["categories"]["rag_retrieval"]["cases"]


def run_experiment():
    # 初始化
    knowledge_path = project_root / config["paths"]["knowledge_file"]
    chunks = load_and_chunk_document(str(knowledge_path))
    chroma_client = chromadb.Client()
    distance = config["rag"].get("distance", "l2")
    collection = chroma_client.get_or_create_collection(
        name="rag_norm_eval",
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
    results_with_norm = []
    results_without_norm = []

    for case in cases:
        q = case["query"]
        expected = case["expected_doc_id"]

        # 有归一化
        ret_norm = retrieve_context(q, context, top_k, score_threshold)
        doc_ids_norm = [r.get("doc_id") for r in ret_norm if r.get("doc_id")]
        hit_top1_norm = len(doc_ids_norm) > 0 and doc_ids_norm[0] == expected
        hit_topk_norm = expected in doc_ids_norm

        # 无归一化
        ret_raw = retrieve_context_raw(q, context, top_k)
        doc_ids_raw = [r["doc_id"] for r in ret_raw]
        hit_top1_raw = len(doc_ids_raw) > 0 and doc_ids_raw[0] == expected
        hit_topk_raw = expected in doc_ids_raw

        # Precision: 相关文档占比（每个 case 的 expected 即相关）
        relevant_set = {expected}
        prec_norm = sum(1 for d in doc_ids_norm if d in relevant_set) / max(len(doc_ids_norm), 1) * 100
        prec_raw = sum(1 for d in doc_ids_raw if d in relevant_set) / max(len(doc_ids_raw), 1) * 100

        results_with_norm.append({
            "id": case["id"],
            "query": q,
            "expected": expected,
            "hit_top1": hit_top1_norm,
            "hit_topk": hit_topk_norm,
            "precision": prec_norm,
            "retrieved": doc_ids_norm,
        })
        results_without_norm.append({
            "id": case["id"],
            "query": q,
            "expected": expected,
            "hit_top1": hit_top1_raw,
            "hit_topk": hit_topk_raw,
            "precision": prec_raw,
            "retrieved": doc_ids_raw,
        })

    return results_with_norm, results_without_norm, cases


def print_report(results_with, results_without, cases):
    def acc(results):
        top1 = sum(1 for r in results if r["hit_top1"]) / len(results) * 100
        topk = sum(1 for r in results if r["hit_topk"]) / len(results) * 100
        return top1, topk

    top1_norm, topk_norm = acc(results_with)
    top1_raw, topk_raw = acc(results_without)
    prec_norm = sum(r["precision"] for r in results_with) / len(results_with)
    prec_raw = sum(r["precision"] for r in results_without) / len(results_without)

    by_cat = {}
    for r in results_with:
        cat = next(c["category"] for c in cases if c["id"] == r["id"])
        by_cat.setdefault(cat, []).append(r)
    for r in results_without:
        cat = next(c["category"] for c in cases if c["id"] == r["id"])
        by_cat.setdefault(cat + "_raw", []).append(r)

    print("=" * 60)
    print("RAG 归一化对比实验")
    print("=" * 60)
    print(f"测试用例数: {len(cases)}")
    print(f"top_k={config['rag']['top_k']}, score_threshold={config['rag']['score_threshold']}")
    print()
    print("【整体指标】")
    print(f"  有归一化: Top-1 {top1_norm:.1f}% Top-k {topk_norm:.1f}% Precision {prec_norm:.1f}%")
    print(f"  无归一化: Top-1 {top1_raw:.1f}% Top-k {topk_raw:.1f}% Precision {prec_raw:.1f}%")
    print()
    print("【分类型统计】")
    for cat in ["exact", "fuzzy", "boundary"]:
        sub_with = [r for r in results_with if next(c for c in cases if c["id"] == r["id"])["category"] == cat]
        sub_without = [r for r in results_without if next(c for c in cases if c["id"] == r["id"])["category"] == cat]
        if not sub_with:
            continue
        t1w, tkw = acc(sub_with)
        t1wo, tkwo = acc(sub_without)
        print(f"  {cat}: 有归一化 Top-1={t1w:.0f}% Top-k={tkw:.0f}%  |  无归一化 Top-1={t1wo:.0f}% Top-k={tkwo:.0f}%")
    print()
    print("【差异分析】")
    diff_top1 = top1_norm - top1_raw
    diff_topk = topk_norm - topk_raw
    diff_prec = prec_norm - prec_raw
    if diff_top1 > 0 or diff_topk > 0 or diff_prec > 0:
        print(f"  归一化优于无归一化: Top-1 +{diff_top1:.1f}%, Top-k +{diff_topk:.1f}%, Precision +{diff_prec:.1f}%")
    elif diff_top1 < 0 or diff_topk < 0 or diff_prec < 0:
        print(f"  无归一化优于归一化: Top-1 {diff_top1:.1f}%, Top-k {diff_topk:.1f}%, Precision {diff_prec:.1f}%")
    else:
        print("  二者表现相当")
    print()
    print("【结论】")
    if abs(diff_top1) < 5 and abs(diff_topk) < 5 and abs(diff_prec) < 5:
        print("  在当前设定下，归一化与无归一化差异不显著。")
    elif diff_prec > 0:
        print("  归一化通过过滤低相关文档提升了 Precision，减少噪声。")
    else:
        better = "有归一化" if (diff_top1 > 0 or diff_topk > 0) else "无归一化"
        print(f"  {better} 在 Top-1/Top-k 上表现更好。")
    print("=" * 60)
    return {
        "top1_norm": top1_norm,
        "topk_norm": topk_norm,
        "prec_norm": prec_norm,
        "top1_raw": top1_raw,
        "topk_raw": topk_raw,
        "prec_raw": prec_raw,
        "diff_top1": top1_norm - top1_raw,
        "diff_topk": topk_norm - topk_raw,
        "diff_prec": prec_norm - prec_raw,
    }


if __name__ == "__main__":
    results_with, results_without, cases = run_experiment()
    metrics = print_report(results_with, results_without, cases)
    out_path = Path(__file__).parent / "rag_norm_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "metrics": metrics,
                "n_cases": len(cases),
                "top_k": config["rag"]["top_k"],
                "score_threshold": config["rag"]["score_threshold"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n结果已保存至: {out_path}")
