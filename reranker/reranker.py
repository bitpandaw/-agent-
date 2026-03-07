"""Reranker 精排：加载 CrossEncoder，对候选做 (query, doc) 精排。"""

from typing import Any, Optional

from config.config_loader import config

_reranker: Optional[Any] = None


def get_reranker() -> Optional[Any]:
    """按配置加载 CrossEncoder，返回实例或 None。懒加载，仅加载一次。"""
    global _reranker
    if _reranker is not None:
        return _reranker
    cfg = config.get("reranker", {}) or {}
    if not cfg.get("enabled") or not cfg.get("model"):
        return None
    try:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(cfg["model"])
        return _reranker
    except Exception as e:
        print(f"Warning: Reranker load failed: {e}, disabling.")
        return None


def is_loaded() -> bool:
    """检查 Reranker 是否已加载。"""
    return get_reranker() is not None


def apply_reranker(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
    model: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """对候选做 Reranker 精排，返回 top_k。

    :param query: 查询文本。
    :param candidates: 候选列表，每项含 text, score 等。
    :param top_k: 返回数量。
    :param model: 若为 None，使用 get_reranker() 获取。
    :return: 重排后的候选列表。
    """
    reranker = model if model is not None else get_reranker()
    if not candidates or reranker is None:
        return candidates[:top_k]
    pairs: list[tuple[str, str]] = [
        (query, c.get("text", "")[:512]) for c in candidates
    ]
    scores: Any = reranker.predict(pairs)
    if hasattr(scores, "tolist"):
        scores = scores.tolist()
    indexed: list[tuple[dict[str, Any], Any]] = list(zip(candidates, scores))
    indexed.sort(key=lambda x: x[1], reverse=True)
    reranked: list[dict[str, Any]] = [c for c, _ in indexed[:top_k]]
    for i, r in enumerate(reranked):
        r["score"] = float(indexed[i][1]) if i < len(indexed) else 0.0
    return reranked
