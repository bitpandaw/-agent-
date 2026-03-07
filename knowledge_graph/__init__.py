"""知识图谱模块。"""

from .kg_retriever import extract_entities, fetch_docs
from .kg_retrieve import retrieve_kg

__all__ = ["extract_entities", "fetch_docs", "retrieve_kg"]

