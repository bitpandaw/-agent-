# tool_registry.py
from sentence_transformers import SentenceTransformer
import sqlite3
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
def query_fault_history(equipment_id=None, fault_type=None):
    conn = sqlite3.connect('fault_history.db')
    cursor = conn.cursor()
    sql = "SELECT * FROM fault_records "
    if equipment_id and fault_type:
        cursor.execute(sql+"WHERE equipment_id = ? AND fault_type = ?",(equipment_id,fault_type))
    elif equipment_id and not fault_type:
        cursor.execute(sql+"WHERE equipment_id = ?",(equipment_id,))
    elif not equipment_id and fault_type:
        cursor.execute(sql+"WHERE fault_type = ?",(fault_type,))
    else :
        cursor.execute(sql+"LIMIT 10")
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
    "query_fault_history":lambda equipment_id, fault_type:query_fault_history(equipment_id,fault_type)
}

# Backward-compatible name
TOOL_REGISTRY = tool_registry
