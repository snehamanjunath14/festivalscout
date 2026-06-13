import os
from dotenv import load_dotenv
load_dotenv()

print("Project endpoint set:", bool(os.getenv("FOUNDRY_PROJECT_ENDPOINT")))
print("Foundry API key set:", bool(os.getenv("FOUNDRY_API_KEY")))
print("AOAI endpoint set:", bool(os.getenv("AZURE_OPENAI_ENDPOINT")))
print("Deployment:", os.getenv("AZURE_OPENAI_DEPLOYMENT"))
print("API version:", os.getenv("AZURE_OPENAI_API_VERSION"))

# Try the direct fallback call so we see the real error
import httpx
ep = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
dep = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
ver = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
key = os.getenv("FOUNDRY_API_KEY", "")
url = f"{ep}/openai/deployments/{dep}/chat/completions?api-version={ver}"
print("\nCalling:", url)
try:
    r = httpx.post(url, headers={"api-key": key, "Content-Type": "application/json"},
                   json={"messages":[{"role":"user","content":"say hi"}],"max_tokens":10}, timeout=30)
    print("Status:", r.status_code)
    print("Response:", r.text[:400])
except Exception as e:
    print("ERROR:", e)