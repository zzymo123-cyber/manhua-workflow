"""测试 PUT /api/settings 端点"""
import http.client
import json

conn = http.client.HTTPConnection("localhost", 8000, timeout=5)

# 1. GET /api/settings
conn.request("GET", "/api/settings")
resp = conn.getresponse()
print(f"GET /api/settings -> {resp.status}")
print(f"  Body: {resp.read().decode()[:200]}")

# 2. PUT /api/settings with body
body = json.dumps({"vidu_api_key": "test123", "idealab_base_url": "https://api.idealab.com/v1"})
conn.request("PUT", "/api/settings", body=body, headers={"Content-Type": "application/json"})
resp = conn.getresponse()
print(f"PUT /api/settings -> {resp.status}")
print(f"  Body: {resp.read().decode()[:200]}")

# 3. PUT /api/settings with empty body
conn.request("PUT", "/api/settings", body="{}", headers={"Content-Type": "application/json"})
resp = conn.getresponse()
print(f"PUT /api/settings (empty) -> {resp.status}")
print(f"  Body: {resp.read().decode()[:200]}")

conn.close()
