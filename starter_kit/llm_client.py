import os
from openai import OpenAI

def chat_completion(messages):
    base_url = os.environ.get("LOOMQ_LLM_BASE_URL")
    api_key = os.environ.get("LOOMQ_LLM_API_KEY")
    model = os.environ.get("LOOMQ_LLM_MODEL")
    
    if not all([base_url, api_key, model]):
        raise RuntimeError("Missing LOOMQ_LLM_* environment variables")
    
    client = OpenAI(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=2048,
    )
    return {"choices": [{"message": {"content": response.choices[0].message.content}}]}
