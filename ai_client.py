import os
import requests
from typing import Optional

BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "google/gemini-2.5-flash-lite"

def get_ai_response(prompt: str, max_tokens: int = 200) -> Optional[str]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENROUTER_API_KEY environment variable")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens
    }
    
    try:
        response = requests.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"AI request failed: {e}")
        return None