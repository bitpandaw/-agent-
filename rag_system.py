from openai import OpenAI
import chromadb
import os
import json
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# 初始化客户端
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1"
)

# 初始化ChromaDB
chroma_client = chromadb.Client()
collection = chroma_client.create_collection(name="equipment_knowledge")
# Step 1: 读取文档并分段
def load_and_chunk_document(filepath):
    """读取文档并按段落分割"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 简单分段：按空行分割
    chunks = [chunk.strip() for chunk in content.split('\n\n') if chunk.strip()]
    return chunks

# Step 2: 把文档块存入ChromaDB
def index_documents(chunks):
    """为文档块生成embedding并存入向量数据库"""
    for i, chunk in enumerate(chunks):
        embedding = model.encode(chunk).tolist()
        collection.add(
            ids=[f"doc_{i}"],
            embeddings=[embedding],
            documents=[chunk]
        )
    print(f"✅ 已索引 {len(chunks)} 个文档块")

# Step 3: RAG检索工具
def search_knowledge(query: str, top_k: int = 2) -> str:
    """根据问题检索相关文档"""
    # 获取query的embedding
    query_embedding = model.encode(query).tolist()
    # 在向量数据库中搜索
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    # 返回检索到的文档
    documents = results['documents'][0]
    return "\n\n---\n\n".join(documents)
 # 定义工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "从设备维护手册中检索相关知识",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要检索的问题或关键词"
                    }
                },
                "required": ["query"]
            }
        }
    }
]
# Step 4: 主Agent循环
def main():
    # 初始化：加载文档
    print("📚 正在加载知识库...")
    chunks = load_and_chunk_document("equipment_knowledge.txt")
    index_documents(chunks)
    conversation = [
        {"role": "system", "content": "你是一个工业设备故障诊断专家。当用户提问时，使用search_knowledge工具从手册中检索相关信息，然后基于检索到的内容给出专业建议。"}
    ]
    
    print("\n=== RAG驱动的设备诊断助手 ===")
    print("(输入 'quit' 退出)\n")
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'quit':
            break
        
        conversation.append({"role": "user", "content": user_input})
        
        # 调用LLM
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=conversation,
            tools=tools
        )
        
        ai_reply = response.choices[0].message
        
        # 处理工具调用
        if ai_reply.tool_calls:
            conversation.append({
                "role": "assistant",
                "content": "",
                "tool_calls": ai_reply.tool_calls
            })
            
            for tool_call in ai_reply.tool_calls:
                if tool_call.function.name == "search_knowledge":
                    query = json.loads(tool_call.function.arguments)["query"]
                    print(f"🔍 正在检索: {query}")
                    
                    # 执行检索
                    retrieved_docs = search_knowledge(query)
                    print(f"📄 找到相关文档片段\n")
                    
                    conversation.append({
                        "role": "tool",
                        "content": retrieved_docs,
                        "tool_call_id": tool_call.id,
                         "name": "search_knowledge"
                    })
            
            # 再次调用LLM生成最终回复
            final_response = client.chat.completions.create(
                model="deepseek-chat",
                messages=conversation,
            )
            ai_reply = final_response.choices[0].message
        
        conversation.append({"role": "assistant", "content": ai_reply.content})
        print(f"\nAI: {ai_reply.content}\n")

if __name__ == "__main__":
    main()