"""Test DeepSeek API connection"""
import os, httpx
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("DEEPSEEK_API_KEY", "")
url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

print(f"URL: {url}/v1/chat/completions")
print(f"Model: {model}")
print(f"Key: {key[:8]}...")

resp = httpx.post(
    f"{url}/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json={
        "model": model,
        "messages": [{"role": "user", "content": "用一句话打招呼"}],
        "temperature": 0.6,
        "max_tokens": 100,
    },
    timeout=15
)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Reply: {data['choices'][0]['message']['content'][:100]}")
