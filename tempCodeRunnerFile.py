rsation,
                tools=tools
            )
            ai_reply = final_response.choices[0].message
        
        conversation.append({"role": "assistant", "content": ai_reply.content})
        print(f"\nAI: {ai_reply.content}\n")