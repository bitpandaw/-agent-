from typing import Any, Dict, List


def load_and_chunk_document(filepath: str) -> List[str]:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 简单分段：按空行分割
    chunks = [chunk.strip() for chunk in content.split('\n\n') if chunk.strip()]
    return chunks

def index_documents(chunks: List[str], context: Dict[str, Any]) :
    embedding_model = context["embedding_model"]
    collection = context["collection"]
    for i, chunk in enumerate(chunks):
        embedding = embedding_model.encode(chunk).tolist()
        collection.add(
            ids=[f"doc_{i}"],
            embeddings=[embedding],
            documents=[chunk]
        )


def retrieve_context(
    query: str,
    context: Dict[str, Any],
    top_k: int,
    score_threshold: float,
) -> List[Dict[str, Any]]:
    """检索时多取候选再做归一化，避免 top_k=2 时第二个结果 norm 恒为 0 被误过滤。"""
    embedding_model = context["embedding_model"]
    query_embedding = embedding_model.encode(query).tolist()
    collection = context["collection"]
    # 多取候选(至少 2*top_k 或 10)，在更大集合上做 min-max 归一化，避免末位恒为 0
    n_candidates = max(10, top_k * 3)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_candidates, collection.count()),
    )
    distances = results.get("distances", [[]])[0]
    documents = results.get("documents", [[]])[0]
    ids = results.get("ids", [[]])[0]
    if not distances:
        return []
    d_min = min(distances)
    d_max = max(distances)
    eps = 1e-8
    final_result = []
    for i, distance in enumerate(distances):
        norm = (d_max - distance) / (d_max - d_min + eps)
        if norm >= score_threshold:
            final_result.append({
                "doc_id": ids[i] if i < len(ids) else None,
                "text": documents[i],
                "score": norm,
            })
    final_result = sorted(final_result, reverse=True, key=lambda x: x["score"])
    return final_result[:top_k]


def retrieve_context_raw(
    query: str,
    context: Dict[str, Any],
    top_k: int,
) -> List[Dict[str, Any]]:
    """无归一化检索：直接按 L2 距离升序返回 top_k，不做 score_threshold 过滤。用于对比实验。"""
    embedding_model = context["embedding_model"]
    collection = context["collection"]
    query_embedding = embedding_model.encode(query).tolist()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )
    distances = results.get("distances", [[]])[0]
    documents = results.get("documents", [[]])[0]
    ids = results.get("ids", [[]])[0]
    if not distances:
        return []
    # 按 L2 距离升序（越小越相似），直接返回，不做归一化
    indexed = list(zip(ids, documents, distances))
    indexed.sort(key=lambda x: x[2])
    return [
        {"doc_id": doc_id, "text": doc, "distance": dist}
        for doc_id, doc, dist in indexed
    ]
