import http.client, json

conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=5)

# GET /api/settings
conn.request("GET", "/api/settings")
r = conn.getresponse()
print(f"GET /api/settings -> {r.status}")
print(f"  Body: {r.read().decode()[:200]}")

# PUT /api/settings
body = json.dumps({"vidu_api_key": "test_live_456"})
conn.request("PUT", "/api/settings", body=body, headers={"Content-Type": "application/json"})
r = conn.getresponse()
print(f"PUT /api/settings -> {r.status}")
print(f"  Body: {r.read().decode()[:200]}")

# GET / to make sure server is alive
conn.request("GET", "/")
r = conn.getresponse()
print(f"GET / -> {r.status}")

conn.close()
