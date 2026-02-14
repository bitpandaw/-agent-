from typing import Any, Dict, List


def load_and_chunk_document(filepath: str) -> List[str]:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 简单分段：按空行分割
    chunks = [chunk.strip() for chunk in content.split('\n\n') if chunk.strip()]
    return chunks

def index_documents(chunks: List[str], context: Dict[str, Any]) :
    model = context["model"]
    collection = context["collection"]
    for i, chunk in enumerate(chunks):
        embedding = model.encode(chunk).tolist()
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
    model = context["model"]
    query_embedding = model.encode(query).tolist()
    collection = context["collection"]
    results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
    )
    distances = results.get("distances",[[]])[0]
    documents = results.get("documents", [[]])[0]
    final_result = []
    for i,distance in enumerate(distances):
        score = 1- distance
        if score>=score_threshold:
            final_result.append({"text":documents[i]
                                 ,"score":score})
    final_result = sorted(final_result,reverse=True,key=lambda x: x["score"])
    return final_result

