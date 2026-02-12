# tool_registry.py
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def calculator(expression: str):
    # Keep eval constrained to avoid arbitrary code execution.
    try:
        return eval(expression, {"__builtins__": {}}, {})
    except Exception as e:
        return f"Calculator error: {e}"

def search_knowledge(query: str, collection, top_k: int = 2) -> str:
    """Search for relevant documents."""
    query_embedding = model.encode(query).tolist()
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
    except Exception as e:
        return f"Vector DB query failed: {e}"

    documents = results.get("documents", [[]])[0]
    if not documents:
        return "No relevant documents found."
    return "Found relevant documents:\n\n" + "\n\n---\n\n".join(documents)


# Tool registry
tool_registry = {
    "search_knowledge": lambda query, collection, top_k=2: search_knowledge(query, collection, top_k),
    "calculator": lambda expression, collection=None: calculator(expression),
}

# Backward-compatible name
TOOL_REGISTRY = tool_registry
