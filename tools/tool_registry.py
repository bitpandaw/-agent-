# tool_registry.py
from sentence_transformers import SentenceTransformer
import sqlite3,time
from config.config_loader import config
from pathlib import Path
_embedding_model = None
def get_embedding_model():
    global _embedding_model 
    if _embedding_model is not None:
        return _embedding_model
    else:
        embedding_model = config["embedding"]
        cache_dir_cfg = embedding_model.get("cache_dir", ".hf_cache")
        cache_dir = Path(cache_dir_cfg)
        if not cache_dir.is_absolute():
            cache_dir = (Path(__file__).resolve().parent.parent / cache_dir).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        _embedding_model = SentenceTransformer(
            embedding_model["model_name"], 
            cache_folder=cache_dir
        )
        return _embedding_model
def calculator(expression: str):
    # Keep eval constrained to avoid arbitrary code execution.
    try:
        return eval(expression, {"__builtins__": {}}, {})
    except Exception as e:
        return f"Calculator error: {e}"

def search_knowledge(query: str, collection, top_k: int = 2) -> str:
    """Search for relevant documents."""
    model = get_embedding_model()
    query_embedding = model.encode(query).tolist()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
        except Exception as e:
            if attempt == max_retries - 1:
                return f"Vector DB query failed after {max_retries} retries: {e}"
            time.sleep(10)
    documents = results.get("documents", [[]])[0]
    if not documents:
        return "No relevant documents found."
    return "Found relevant documents:\n\n" + "\n\n---\n\n".join(documents)
def query_fault_history(equipment_id=None, fault_type=None):
    conn = sqlite3.connect('fault_history.db')
    cursor = conn.cursor()
    params = ()
    sql = "SELECT * FROM fault_records "
    if equipment_id and fault_type:
        sql+="WHERE equipment_id = ? AND fault_type = ?"
        params = (equipment_id, fault_type)
    elif equipment_id and not fault_type:
        sql+="WHERE equipment_id = ?"
        params = (equipment_id,)
    elif not equipment_id and fault_type:
        sql+="WHERE fault_type = ?"
        params = (fault_type,)
    else :
       sql+="LIMIT 10"
    cursor.execute(sql,params)
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return "未找到符合条件的故障记录"
    lines = [f"找到{len(rows)}条记录："]
    for i,row in enumerate(rows, 1):
        _,ft,date,sol,hours,eq =row
        lines.append(f"{i}. {eq} - {ft} - {date} - 解决方案：{sol} - 停机{hours}小时")
    conn.close()
    return "\n".join(lines)

# Tool registry
tool_registry = {
    "search_knowledge": lambda query, collection, top_k=2: search_knowledge(query, collection, top_k),
    "calculator": lambda expression, collection=None: calculator(expression),
    "query_fault_history": lambda equipment_id=None, fault_type=None, collection=None: query_fault_history(
        equipment_id=equipment_id,
        fault_type=fault_type
    )
}

# Backward-compatible name
TOOL_REGISTRY = tool_registry
