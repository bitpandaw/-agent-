# tools_json.py
TOOLS_LIST = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a math expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Expression to evaluate, e.g. '25*4'."
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the Wikipedia knowledge base (vector retrieval).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_qa_records",
            "description": "Query historical Q&A records by article title or keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "article_title": {
                        "type": "string",
                        "description": "Filter by article title (optional)"
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Search in question/answer text (optional)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_article_graph",
            "description": "Query the article knowledge graph for multi-hop reasoning. Use article_title for exact article lookup, or query for keyword search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "article_title": {
                        "type": "string",
                        "description": "Exact article title (optional)"
                    },
                    "query": {
                        "type": "string",
                        "description": "Keyword to search in article/sentence (optional)"
                    }
                }
            }
        }
    },
]
