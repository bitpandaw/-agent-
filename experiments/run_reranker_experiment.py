"""RAG、RAG+Reranker、RAG+KG、RAG+KG+Reranker 对比实验。

输出 hit@k、recall@k、precision@k、mrr、ndcg、map、coverage。

用法：
  1. 确保 Embedding(8011)、RAG(8010)、Neo4j 已启动
  2. python experiments/run_reranker_experiment.py
  3. 结果写入 experiments/results/reranker_summary.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RAG_URL = "http://localhost:8010/retrieve"
MAX_SAMPLES = 100
TOP_KS = [1, 5, 10, 20]


def _fetch_kg(query: str) -> list[dict]:
    """从 Neo4j KG 按 query 检索，返回 [{text}, ...]。"""
    try:
        from config.config_loader import config
        from neo4j import GraphDatabase

        cfg = config["neo4j"]
        driver = GraphDatabase.driver(
            cfg["uri"], auth=(cfg["user"], cfg["password"])
        )
        cypher = (
            "MATCH (a:Article)-[:CONTAINS]->(s:Sentence) "
            "WHERE s.text CONTAINS $query OR a.title CONTAINS $query "
            "RETURN a.title AS article, s.text AS sentence LIMIT 15"
        )
        with driver.session() as session:
            recs = session.run(cypher, query=query).data()
        driver.close()
        return [{"text": r["sentence"], "doc_id": f"kg_{r['article']}"} for r in recs]
    except Exception:
        return []


def load_hotpotqa():
    """加载 HotpotQA validation，返回 (question, relevant_texts) 列表。"""
    try:
        from datasets import load_dataset
    except ImportError:
        print("pip install datasets")
        sys.exit(1)
    ds = load_dataset("hotpot_qa", "distractor", split="validation", trust_remote_code=False)
    samples = []
    for i in range(min(MAX_SAMPLES, len(ds))):
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


def compute_metrics(retrieved: list, relevant_texts: set[str], k_values: list[int]) -> dict:
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


def main() -> None:
    samples = load_hotpotqa()
    print(f"Loaded {len(samples)} samples from HotpotQA validation")

    variants = [
        ("rag_only", False, False),
        ("rag_reranker", True, False),
        ("rag_kg", False, True),
        ("rag_kg_reranker", True, True),
    ]
    results = {}

    for name, use_reranker, use_kg in variants:
        print(f"Running {name}...")
        samples_metrics = []
        for q, rel in samples:
            retrieved = []
            try:
                resp = httpx.post(
                    RAG_URL,
                    json={"query": q, "use_reranker": use_reranker},
                    timeout=60,
                )
                resp.raise_for_status()
                rag = resp.json()
                if isinstance(rag, list):
                    retrieved = list(rag)
            except Exception as e:
                print(f"  Error RAG: {e}")
            if use_kg:
                kg_docs = _fetch_kg(q)
                seen = {d.get("text", "")[:100] for d in retrieved}
                for d in kg_docs:
                    if d.get("text", "")[:100] not in seen:
                        retrieved.append(d)
                        seen.add(d.get("text", "")[:100])
            metrics = compute_metrics(retrieved, rel, TOP_KS)
            samples_metrics.append(metrics)
        results[name] = aggregate(samples_metrics, TOP_KS)
        print(
            f"  {name}: hit@1={results[name].get('hit@1', 0):.2f} "
            f"mrr={results[name].get('mrr', 0):.2f}"
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "reranker_summary.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
