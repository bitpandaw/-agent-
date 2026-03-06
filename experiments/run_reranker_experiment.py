"""RAG+Reranker、RAG+KG+Reranker 对比实验。

输出 hit@k、recall@k、precision@k、mrr、ndcg、map、coverage。

用法：
  1. 确保 Embedding(8011)、RAG(8010)、Neo4j 已启动
  2. python experiments/run_reranker_experiment.py
  3. 结果写入 experiments/results/reranker_summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RAG_URL = "http://localhost:8010/retrieve"
MAX_SAMPLES = 50
TOP_KS = [1, 5, 10, 20, 30]
TOP_K = max(TOP_KS)
DEFAULT_WORKERS = 8


def _fetch_rag(
    client: httpx.Client,
    query: str,
    use_reranker: bool,
    use_kg: bool,
) -> list[dict]:
    try:
        resp = client.post(
            RAG_URL,
            json={
                "query": query,
                "use_reranker": use_reranker,
                "use_kg": use_kg,
            },
            timeout=60,
        )
        resp.raise_for_status()
        rag = resp.json()
        if isinstance(rag, list):
            return list(rag)
    except Exception as e:
        print(f"  Error RAG: {e}")
    return []


def load_hotpotqa(max_samples: int):
    """加载 HotpotQA validation，返回 (question, relevant_texts) 列表。"""
    try:
        from datasets import load_dataset
    except ImportError:
        print("pip install datasets")
        sys.exit(1)
    ds = load_dataset("hotpot_qa", "distractor", split="validation", trust_remote_code=False)
    samples = []
    for i in range(min(max_samples, len(ds))):
        s = ds[i]
        ctx_titles = s["context"]["title"]
        ctx_sentences = s["context"]["sentences"]
        sf_titles = s["supporting_facts"]["title"]
        sf_sent_ids = s["supporting_facts"]["sent_id"]
        relevant = set()
        for t, sid in zip(sf_titles, sf_sent_ids):
            for ct, sents in zip(ctx_titles, ctx_sentences):
                if ct == t and sid < len(sents):
                    relevant.add(str(sents[sid]).strip())
                    break
        if relevant:
            samples.append((s["question"], relevant))
    return samples


def _is_relevant(doc_text: str, relevant_texts: set[str]) -> bool:
    """判断检索 doc 是否命中任一相关句。"""
    t = (doc_text or "").strip()
    for r in relevant_texts:
        if r in t or t in r or (len(r) > 20 and r[:50] in t):
            return True
    return False


def compute_metrics(
    retrieved: list, relevant_texts: set[str], k_values: list[int]
) -> dict:
    """计算 hit@k, recall@k, precision@k, mrr@k, ndcg@k, map@k, coverage@k。"""
    rel_list = list(relevant_texts)
    hit_rel = [i for i, d in enumerate(retrieved) if _is_relevant(d.get("text", ""), relevant_texts)]
    metrics = {}
    for k in k_values:
        top_k = retrieved[:k]
        hits = sum(1 for d in top_k if _is_relevant(d.get("text", ""), relevant_texts))
        metrics[f"hit@{k}"] = 1.0 if hits > 0 else 0.0
        metrics[f"recall@{k}"] = hits / len(rel_list) if rel_list else 0.0
        metrics[f"precision@{k}"] = hits / k if k > 0 else 0.0
        metrics[f"coverage@{k}"] = 1.0 if hits > 0 else 0.0
        mrr = 0.0
        for r in hit_rel:
            if r < k:
                mrr = 1.0 / (r + 1)
                break
        metrics[f"mrr@{k}"] = mrr
        dcg = sum(
            1.0 / (i + 2)
            for i, d in enumerate(top_k)
            if _is_relevant(d.get("text", ""), relevant_texts)
        )
        idcg = sum(1.0 / (i + 2) for i in range(min(len(rel_list), k)))
        metrics[f"ndcg@{k}"] = dcg / idcg if idcg > 0 else 0.0
        ap = 0.0
        rel_seen = 0
        for i, d in enumerate(top_k):
            if _is_relevant(d.get("text", ""), relevant_texts):
                rel_seen += 1
                ap += rel_seen / (i + 1)
        metrics[f"map@{k}"] = ap / len(rel_list) if rel_list else 0.0
    return metrics


def aggregate(samples_metrics: list[dict], k_values: list[int]) -> dict:
    """聚合多样本的指标。"""
    if not samples_metrics:
        return {}
    keys = [
        *[f"hit@{k}" for k in k_values],
        *[f"recall@{k}" for k in k_values],
        *[f"precision@{k}" for k in k_values],
        *[f"mrr@{k}" for k in k_values],
        *[f"ndcg@{k}" for k in k_values],
        *[f"map@{k}" for k in k_values],
        *[f"coverage@{k}" for k in k_values],
    ]
    out = {}
    for key in keys:
        vals = [m.get(key, 0) for m in samples_metrics]
        out[key] = sum(vals) / len(vals) if vals else 0.0
    return out


def _process_one(
    client: httpx.Client,
    q: str,
    rel: set[str],
    use_reranker: bool,
    use_kg: bool,
    top_ks: list[int],
) -> dict:
    rag = _fetch_rag(client, q, use_reranker, use_kg)
    return compute_metrics(rag, rel, top_ks)


def run_variant(
    name: str,
    use_reranker: bool,
    use_kg: bool,
    samples: list[tuple[str, set[str]]],
    top_ks: list[int],
    workers: int,
) -> dict:
    print(f"Running {name}...")
    samples_metrics: list[dict] = []
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [
                ex.submit(
                    _process_one,
                    client,
                    q,
                    rel,
                    use_reranker,
                    use_kg,
                    top_ks,
                )
                for q, rel in samples
            ]
            for i, f in enumerate(as_completed(futures), 1):
                samples_metrics.append(f.result())
                if i % 10 == 0 or i == len(futures):
                    print(f"  {name}: {i}/{len(futures)} done")
    return aggregate(samples_metrics, top_ks)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--max-samples", type=int, default=MAX_SAMPLES)
    p.add_argument("--top-ks", type=str, default="1,5,10,20,30")
    p.add_argument(
        "--variant",
        type=str,
        default="all",
        choices=["all", "rag_reranker", "rag_kg_reranker"],
    )
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--out", type=str, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    top_ks = [int(x) for x in args.top_ks.split(",") if x.strip()]
    top_ks = sorted(set(top_ks))
    top_k = max(top_ks) if top_ks else TOP_K
    samples = load_hotpotqa(args.max_samples)
    print(f"Loaded {len(samples)} samples from HotpotQA validation")
    print(f"Evaluating top_ks={top_ks} (pipeline returns up to config.rag.top_k)")

    variants = [
        ("rag_reranker", True, False),
        ("rag_kg_reranker", True, True),
    ]
    active = [
        (name, use_reranker, use_kg)
        for name, use_reranker, use_kg in variants
        if args.variant == "all" or name == args.variant
    ]
    results: dict[str, dict] = {}

    if len(active) > 1:
        total_workers = max(1, args.workers)
        base = max(1, total_workers // len(active))
        remainder = total_workers - base * len(active)
        if total_workers < len(active):
            print(
                f"Warning: workers={total_workers} < variants={len(active)}, "
                "effective total concurrency will exceed workers."
            )
        per_variant_workers = [
            base + (1 if i < remainder else 0) for i in range(len(active))
        ]
        print(
            "Running variants in parallel "
            f"(total_workers={total_workers}, per_variant={per_variant_workers})"
        )
        with ThreadPoolExecutor(max_workers=len(active)) as ex:
            futures = {}
            for i, (name, use_reranker, use_kg) in enumerate(active):
                futures[
                    ex.submit(
                        run_variant,
                        name,
                        use_reranker,
                        use_kg,
                        samples,
                        top_ks,
                        per_variant_workers[i],
                    )
                ] = name
            for f in as_completed(futures):
                name = futures[f]
                results[name] = f.result()
                print(
                    f"  {name}: hit@1={results[name].get('hit@1', 0):.2f} "
                    f"mrr@{top_k}={results[name].get(f'mrr@{top_k}', 0):.2f}"
                )
    else:
        for name, use_reranker, use_kg in active:
            results[name] = run_variant(
                name,
                use_reranker,
                use_kg,
                samples,
                top_ks,
                max(1, args.workers),
            )
            print(
                f"  {name}: hit@1={results[name].get('hit@1', 0):.2f} "
                f"mrr@{top_k}={results[name].get(f'mrr@{top_k}', 0):.2f}"
            )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = (
        Path(args.out)
        if args.out
        else RESULTS_DIR / "reranker_summary.json"
    )
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
