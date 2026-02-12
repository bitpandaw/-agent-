# tool_registry.py
from sentence_transformers import SentenceTransformer
import sqlite3
from config.config_loader import config
from pathlib import Path
embedding_model = config["embedding"]
cache_dir_cfg = embedding_model.get("cache_dir", ".hf_cache")
cache_dir = Path(cache_dir_cfg)
model = SentenceTransformer(
    embedding_model["model_name"], 
    cache_folder=embedding_model["cache_dir"]
)
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
        raise Exception(f"Vector DB query failed: {e}")

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
