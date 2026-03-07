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
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
) -> tuple[list[dict], dict[str, Any]]:
    t0 = time.perf_counter()
    status_code: int | None = None
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
        status_code = resp.status_code
        resp.raise_for_status()
        rag = resp.json()
        if isinstance(rag, list):
            return list(rag), {
                "ok": True,
                "status_code": status_code,
                "latency_ms": (time.perf_counter() - t0) * 1000,
                "error": None,
            }
        return [], {
            "ok": False,
            "status_code": status_code,
            "latency_ms": (time.perf_counter() - t0) * 1000,
            "error": "Non-list response",
        }
    except Exception as e:
        return [], {
            "ok": False,
            "status_code": status_code,
            "latency_ms": (time.perf_counter() - t0) * 1000,
            "error": str(e),
        }


def load_hotpotqa(max_samples: int) -> list[dict[str, Any]]:
    """加载 HotpotQA validation，返回 {id, idx, question, relevant_texts} 列表。"""
    try:
        from datasets import load_dataset
    except ImportError:
        print("pip install datasets")
        sys.exit(1)
    ds = load_dataset("hotpot_qa", "distractor", split="validation", trust_remote_code=False)
    samples: list[dict[str, Any]] = []
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
            sample_id = s.get("_id") or s.get("id") or str(i)
            samples.append(
                {
                    "id": sample_id,
                    "idx": i,
                    "question": s["question"],
                    "relevant_texts": relevant,
                }
            )
    return samples


def _is_relevant(doc_text: str, relevant_texts: set[str]) -> bool:
    """判断检索 doc 是否命中任一相关句。"""
    t = (doc_text or "").strip()
    for r in relevant_texts:
        if r in t or t in r or (len(r) > 20 and r[:50] in t):
            return True
    return False


def compute_metrics(
    retrieved: list[dict[str, Any]], relevant_texts: set[str], k_values: list[int]
) -> dict[str, float]:
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


def aggregate(samples_metrics: list[dict[str, float]], k_values: list[int]) -> dict[str, float]:
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


def _compact_results(
    results: list[dict],
    top_n: int,
    max_text_chars: int,
) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for d in results[:top_n]:
        text = (d.get("text") or "").replace("\n", " ").strip()
        if max_text_chars > 0 and len(text) > max_text_chars:
            text = text[:max_text_chars] + "..."
        compact.append(
            {
                "doc_id": d.get("doc_id"),
                "score": d.get("score"),
                "text": text,
            }
        )
    return compact


def _signature(results: list[dict], top_k: int) -> list[str]:
    sig = []
    for d in results[:top_k]:
        doc_id = d.get("doc_id")
        if doc_id:
            sig.append(str(doc_id))
        else:
            text = (d.get("text") or "").replace("\n", " ").strip()
            sig.append(text[:80])
    return sig


def _pctl(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    vals = sorted(vals)
    idx = int(round((p / 100.0) * (len(vals) - 1)))
    return float(vals[max(0, min(idx, len(vals) - 1))])


def _safe_git_head() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def _load_config_snapshot() -> str | None:
    cfg_path = ROOT / "config" / "config.yaml"
    if not cfg_path.exists():
        return None
    return cfg_path.read_text(encoding="utf-8", errors="replace")


def _process_one(
    client: httpx.Client,
    sample: dict[str, Any],
    use_reranker: bool,
    use_kg: bool,
    top_ks: list[int],
    trace_top_n: int,
    trace_text_chars: int,
    variant_name: str,
) -> dict:
    q = sample["question"]
    rel = sample["relevant_texts"]
    rag, meta = _fetch_rag(client, q, use_reranker, use_kg)
    metrics = compute_metrics(rag, rel, top_ks)
    return {
        "metrics": metrics,
        "meta": meta,
        "sample": sample,
        "results": rag,
        "trace": {
            "variant": variant_name,
            "sample_id": sample["id"],
            "idx": sample["idx"],
            "question": q,
            "relevant_texts": list(rel),
            "result_count": len(rag),
            "http": meta,
            "top_results": _compact_results(rag, trace_top_n, trace_text_chars),
            "metrics": metrics,
        },
    }


def run_variant(
    name: str,
    use_reranker: bool,
    use_kg: bool,
    samples: list[dict[str, Any]],
    top_ks: list[int],
    workers: int,
    trace_enabled: bool,
    trace_path: Path | None,
    trace_top_n: int,
    trace_text_chars: int,
    signature_k: int,
) -> tuple[dict, dict[str, Any], dict[str, list[str]]]:
    print(f"Running {name}...")
    samples_metrics: list[dict] = []
    latencies: list[float] = []
    error_count = 0
    empty_count = 0
    signatures: dict[str, list[str]] = {}
    trace_f = None
    if trace_enabled and trace_path is not None:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_f = trace_path.open("w", encoding="utf-8")
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [
                ex.submit(
                    _process_one,
                    client,
                    sample,
                    use_reranker,
                    use_kg,
                    top_ks,
                    trace_top_n,
                    trace_text_chars,
                    name,
                )
                for sample in samples
            ]
            for i, f in enumerate(as_completed(futures), 1):
                result = f.result()
                samples_metrics.append(result["metrics"])
                meta = result["meta"]
                if not meta.get("ok"):
                    error_count += 1
                else:
                    latencies.append(float(meta.get("latency_ms", 0.0)))
                if result["trace"]["result_count"] == 0:
                    empty_count += 1
                sig = _signature(result["results"], signature_k)
                signatures[str(result["sample"]["id"])] = sig
                if trace_f is not None:
                    trace_f.write(
                        json.dumps(result["trace"], ensure_ascii=False) + "\n"
                    )
                if i % 10 == 0 or i == len(futures):
                    print(f"  {name}: {i}/{len(futures)} done")
    if trace_f is not None:
        trace_f.close()
    stats = {
        "count": len(samples_metrics),
        "errors": error_count,
        "empty_results": empty_count,
        "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else 0.0,
        "p95_latency_ms": _pctl(latencies, 95.0),
    }
    return aggregate(samples_metrics, top_ks), stats, signatures


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-samples", type=int, default=MAX_SAMPLES)
    parser.add_argument("--top-ks", type=str, default="1,5,10,20,30")
    parser.add_argument(
        "--variant",
        type=str,
        default="all",
        choices=["all", "rag_reranker", "rag_kg_reranker"],
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--out", type=str, default=None)
    return parser.parse_args()


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
