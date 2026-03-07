"""Ragas RAG 四配置对照实验。

纯 RAG、RAG+Reranker、RAG+KG、RAG+Reranker+KG 对比，使用 Context Precision / Context Recall。

用法：
  1. 配置 DEEPSEEK_API_KEY（KG variant 还需 Neo4j 在线）
  2. pip install -r experiments/requirements.txt
  3. python experiments/run_ragas_experiment.py
  4. 结果写入 experiments/results/ragas_summary.json

注意：检索直接在进程内通过本地 import 完成，无需启动任何 HTTP 服务。
"""

from __future__ import annotations

import argparse
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS_DIR = Path(__file__).resolve().parent / "results"
MAX_SAMPLES = 50
VARIANTS = [
    ("rag", False, False),
    ("rag_reranker", True, False),
    ("rag_kg", False, True),
    ("rag_kg_reranker", True, True),
]


class _LocalRetriever:
    """懒加载单例，封装 SentenceTransformer + ChromaDB，避免重复初始化。"""

    _instance: "_LocalRetriever | None" = None

    def __init__(self) -> None:
        from config.config_loader import config
        import chromadb
        from sentence_transformers import SentenceTransformer

        cfg_emb = config["embedding"]
        cfg_rag = config["rag"]
        cfg_paths = config["paths"]

        cache_dir = str(ROOT / cfg_emb.get("cache_dir", ".hf_cache"))
        self.model = SentenceTransformer(cfg_emb["model_name"], cache_folder=cache_dir)

        chroma_path = str(ROOT / cfg_paths.get("chroma_dir", "chroma_db"))
        chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = chroma_client.get_or_create_collection(
            name=cfg_rag["collection_name"],
            metadata={"hnsw:space": cfg_rag.get("distance", "cosine")},
        )
        self.top_k: int = int(cfg_rag.get("top_k", 5))
        print(f"[LocalRetriever] 初始化完成：collection={cfg_rag['collection_name']} "
              f"docs={self.collection.count()} top_k={self.top_k}")

    @classmethod
    def get(cls) -> "_LocalRetriever":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def embed(self, text: str) -> list[float]:
        return self.model.encode([text])[0].tolist()

    @staticmethod
    def _strip_title(text: str) -> str:
        """剥掉 ChromaDB chunk 的 'Title: xxx\n\n' 头部，只保留正文。"""
        if text.startswith("Title:"):
            # 跳过第一行（标题行）以及紧随的空行
            parts = text.split("\n", 1)
            body = parts[1].lstrip("\n") if len(parts) > 1 else ""
            return body if body else text
        return text

    def retrieve(self, query: str, n_candidates: int) -> list[dict[str, Any]]:
        """向量检索，返回 [{doc_id, text, score}, ...] 按 score 降序。
        text 已去除 'Title:' 前缀，只保留正文，以便与 HotpotQA Ground Truth 对齐。
        """
        vec = self.embed(query)
        n = min(n_candidates, self.collection.count())
        if n == 0:
            return []
        results = self.collection.query(query_embeddings=[vec], n_results=n)
        distances: list[float] = results.get("distances", [[]])[0]
        documents: list[str] = results.get("documents", [[]])[0]
        ids: list[str] = results.get("ids", [[]])[0]
        candidates = [
            {"doc_id": ids[i], "text": self._strip_title(documents[i]), "score": -distances[i]}
            for i in range(len(distances))
        ]
        return sorted(candidates, key=lambda x: x["score"], reverse=True)


def load_hotpotqa_ragas(max_samples: int) -> list[dict[str, Any]]:
    """加载 HotpotQA validation，返回 {id, idx, question, answer, relevant_texts}。"""
    try:
        from datasets import load_dataset
    except ImportError:
        print("pip install datasets")
        sys.exit(1)
    ds = load_dataset(
        "hotpot_qa", "distractor", split="validation", trust_remote_code=False
    )
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
            answer = s.get("answer", "")
            if isinstance(answer, list):
                answer = answer[0] if answer else ""
            samples.append(
                {
                    "id": sample_id,
                    "idx": i,
                    "question": s["question"],
                    "answer": str(answer).strip() if answer else "",
                    "relevant_texts": relevant,
                }
            )
    return samples


def fetch_rag(
    query: str,
    use_reranker: bool,
    use_kg: bool,
    debug: bool = False,
) -> tuple[list[str], list[dict[str, Any]]]:
    """本地检索：直接 import ChromaDB + SentenceTransformer，不走 HTTP。

    流程：向量召回 → (可选 KG 召回) → 合并去重 → (可选全局 Reranker) → top-k 截断。
    """
    retriever = _LocalRetriever.get()
    top_k = retriever.top_k

    # ① 向量召回（多取候选，留给 Reranker 足够的排序空间）
    n_candidates = max(20, top_k * 5) if use_reranker else max(10, top_k * 3)
    vector_candidates = retriever.retrieve(query, n_candidates)
    ctxs: list[str] = [c["text"] for c in vector_candidates]

    if debug:
        print(f"    [DEBUG] 向量召回数量: {len(ctxs)}")
        if ctxs:
            print(f"    [DEBUG] 首段前80字: {ctxs[0][:80]}")

    # ② KG 召回（直接 import kg_retrieve）
    kg_raw: list[dict[str, Any]] = []
    kg_texts: list[str] = []
    if use_kg:
        try:
            from knowledge_graph.kg_retrieve import retrieve_kg
            kg_cfg = __import__("config.config_loader", fromlist=["config"]).config.get("kg", {})
            kg_top_k = int(kg_cfg.get("top_k", top_k * 2))
            kg_raw = retrieve_kg(query, top_k=kg_top_k)
            kg_texts = [d.get("text", "") or "" for d in kg_raw]
            if debug:
                print(f"    [DEBUG] KG 召回数量: {len(kg_texts)}")
        except Exception as e:
            if debug:
                print(f"    [DEBUG] KG 召回失败: {e}")

    # ③ 合并去重
    merged_texts: list[str] = []
    seen: set[str] = set()
    for text in ctxs + kg_texts:
        if text and text not in seen:
            seen.add(text)
            merged_texts.append(text)

    # ④ 全局 Reranker（仅 use_reranker=True 时）
    if use_reranker and merged_texts:
        try:
            from reranker import apply_reranker, get_reranker
            reranker_model = get_reranker()
            if reranker_model:
                candidates = [{"text": t, "score": 0.0} for t in merged_texts]
                reranked = apply_reranker(query, candidates, top_k, model=reranker_model)
                merged_texts = [r.get("text", "") for r in reranked]
                if debug:
                    print(f"    [DEBUG] Reranker 重排后数量: {len(merged_texts)}")
        except Exception as e:
            if debug:
                print(f"    [DEBUG] 全局重排失败: {e}")

    # ⑤ 统一截断
    merged_texts = merged_texts[:top_k]
    return merged_texts, kg_raw


def run_ragas_eval(
    variant_name: str,
    samples: list[dict[str, Any]],
    use_reranker: bool,
    use_kg: bool,
    debug: bool = False,
) -> dict[str, Any]:
    """对单个 variant 执行 Ragas 评估。"""
    from config.config_loader import config
    from ragas import evaluate
    from ragas.metrics import context_precision, context_recall

    llm_cfg = config["llm"]
    api_key = os.environ.get(llm_cfg["api_key_env"], "")
    base_url = llm_cfg.get("base_url", "https://api.deepseek.com/v1")

    if debug:
        print(f"    [DEBUG] DEEPSEEK_API_KEY 已配置: {bool(api_key and api_key.strip())}")

    from openai import OpenAI
    from ragas.llms import llm_factory

    client = OpenAI(api_key=api_key, base_url=base_url)
    llm = llm_factory("deepseek-chat", provider="openai", client=client)

    kg_debug: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    for i, sample in enumerate(samples):
        ctxs, kg_raw = fetch_rag(
            sample["question"],
            use_reranker,
            use_kg,
            debug=debug and i == 0,
        )
        ref = sample.get("answer", "") or ""
        ref_ctxs = list(sample.get("relevant_texts", []))
        rows.append(
            {
                "user_input": sample["question"],
                "retrieved_contexts": ctxs,
                "reference_contexts": ref_ctxs if ref_ctxs else [ref],
                "reference": ref,
                "response": ref,
            }
        )
        if debug and i == 0 and use_kg:
            try:
                from config.config_loader import config as cfg
                from knowledge_graph.kg_retriever import extract_entities
                kg_cfg = cfg.get("kg", {}) or {}
                entities = extract_entities(
                    sample["question"],
                    int(kg_cfg.get("max_entities", 6)),
                    int(kg_cfg.get("max_keywords", 6)),
                )
                paths = []
                for d in kg_raw:
                    doc_id = d.get("doc_id", "")
                    hop = d.get("hop", 0)
                    if doc_id.startswith("kg1_"):
                        art = doc_id[4:]
                        paths.append(f"Hop1: Entity→{art} (sentence)")
                    elif doc_id.startswith("kg2_"):
                        rest = doc_id[5:]
                        if "__" in rest:
                            a1, a2 = rest.split("__", 1)
                            paths.append(f"Hop2: {a1} -[CO_OCCURS]-> {a2}")
                kg_debug = {
                    "entities": entities,
                    "kg_doc_count": len(kg_raw),
                    "paths": paths,
                    "kg_docs": [
                        {"doc_id": d.get("doc_id"), "hop": d.get("hop"), "text_preview": (d.get("text") or "")[:80]}
                        for d in kg_raw[:10]
                    ],
                }
            except Exception as e:
                kg_debug = {"error": str(e)}
        if debug and i == 0:
            print(f"    [DEBUG] 首条 retrieved_contexts 数量: {len(ctxs)}")
            if ctxs:
                print(f"    [DEBUG] 首条第1段长度: {len(ctxs[0])} 字符")
        if (i + 1) % 10 == 0:
            print(f"  {variant_name}: fetched {i + 1}/{len(samples)}")


    if debug and rows:
        sample_row = rows[0]
        sample = samples[0]
        print("    [DEBUG] 首条样本:")
        print("      question:", sample_row["user_input"][:120])
        print("      reference:", sample_row["reference"])
        print("      relevant_texts (Ground Truth):", list(sample.get("relevant_texts", []))[:2])
        print("      retrieved_contexts 数量:", len(sample_row["retrieved_contexts"]))
        for j, ctx in enumerate(sample_row["retrieved_contexts"][:3]):
            print(f"      ctx[{j}] (前80字):", (ctx or "")[:80])
        if kg_debug:
            print("    [DEBUG] Neo4j KG 链路:")
            print("      entities:", kg_debug.get("entities", []))
            print("      kg_doc_count:", kg_debug.get("kg_doc_count", 0))
            for p in kg_debug.get("paths", [])[:8]:
                print("      ", p)
            debug_kg_path = RESULTS_DIR / "debug_kg_paths.json"
            debug_kg_path.write_text(
                json.dumps(kg_debug, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"    [DEBUG] KG 链路已写入: {debug_kg_path}")
        debug_path = RESULTS_DIR / "debug_sample.json"
        debug_path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"    [DEBUG] 全部 {len(rows)} 条样本已写入: {debug_path}")

    try:
        from ragas import EvaluationDataset

        dataset = EvaluationDataset.from_list(rows)
    except Exception:
        import pandas as pd

        df = pd.DataFrame(rows)
        from ragas import EvaluationDataset

        dataset = EvaluationDataset.from_pandas(df)

    if debug:
        print("    [DEBUG] 测试 LLM 连通性...")
        try:
            test_resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "say ok"}],
                max_tokens=5,
            )
            print(f"    [DEBUG] LLM 连通性 OK: {test_resp.choices[0].message.content[:20]}")
        except Exception as e:
            print(f"    [DEBUG] LLM 连通性失败: {e}")
            return {"count": len(samples), "context_precision": 0.0, "context_recall": 0.0}

    metrics = [context_precision, context_recall]
    if debug:
        print("    [DEBUG] 开始 Ragas evaluate（首次调用可能需 10-30 秒）...")
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        show_progress=True,
    )

    out: dict[str, Any] = {"count": len(samples)}
    for k in ["context_precision", "context_recall"]:
        v = result.get(k) if isinstance(result, dict) else getattr(result, k, None)
        out[k] = float(v) if v is not None else 0.0
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-samples", type=int, default=MAX_SAMPLES)
    parser.add_argument(
        "--variant",
        type=str,
        default="all",
        choices=["all", "rag", "rag_reranker", "rag_kg", "rag_kg_reranker"],
    )
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument("--debug", action="store_true", help="打印调试信息")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = load_hotpotqa_ragas(args.max_samples)
    print(f"Loaded {len(samples)} samples from HotpotQA validation")

    active = [
        (name, ur, uk)
        for name, ur, uk in VARIANTS
        if args.variant == "all" or name == args.variant
    ]

    results: dict[str, dict[str, Any]] = {}
    for name, use_reranker, use_kg in active:
        print(f"Running {name}...")
        results[name] = run_ragas_eval(
            name, samples, use_reranker, use_kg, debug=args.debug
        )
        r = results[name]
        print(
            f"  {name}: context_precision={r.get('context_precision', 0):.4f} "
            f"context_recall={r.get('context_recall', 0):.4f}"
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else RESULTS_DIR / "ragas_summary.json"
    out_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
