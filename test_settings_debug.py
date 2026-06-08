"""测试设置保存功能"""
import sys
sys.stdout.write("Starting test...\n")
sys.stdout.flush()

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# 测试 GET /api/settings
resp = client.get("/api/settings")
sys.stdout.write(f"GET status: {resp.status_code}\n")
sys.stdout.write(f"GET body: {resp.text[:200]}\n")
sys.stdout.flush()

# 测试 PUT /api/settings
resp = client.put("/api/settings", json={
    "vidu_api_key": "test_vidu_key",
    "wetoken_api_key": "test_wetoken_key",
    "idealab_api_key": "test_idealab_key",
    "idealab_base_url": "https://api.idealab.com/v1"
})
sys.stdout.write(f"PUT status: {resp.status_code}\n")
sys.stdout.write(f"PUT body: {resp.text[:200]}\n")
sys.stdout.flush()

# 再 GET 确认保存成功
resp = client.get("/api/settings")
sys.stdout.write(f"GET after PUT status: {resp.status_code}\n")
data = resp.json()
sys.stdout.write(f"has_vidu: {data.get('_has_vidu')}, has_wetoken: {data.get('_has_wetoken')}, has_idealab: {data.get('_has_idealab')}\n")
sys.stdout.flush()

# 测试空 body PUT
resp = client.put("/api/settings", json={})
sys.stdout.write(f"PUT empty status: {resp.status_code}\n")
sys.stdout.write(f"PUT empty body: {resp.text[:200]}\n")
sys.stdout.flush()

# 测试只有 base_url 的 PUT
resp = client.put("/api/settings", json={"idealab_base_url": "https://api.idealab.com/v1"})
sys.stdout.write(f"PUT only url status: {resp.status_code}\n")
sys.stdout.write(f"PUT only url body: {resp.text[:200]}\n")
sys.stdout.flush()

sys.stdout.write("Done!\n")
sys.stdout.flush()
