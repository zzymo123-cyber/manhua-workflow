import sys
from fastapi.testclient import TestClient
from main import app

c = TestClient(app)

# GET
r = c.get("/api/settings")
with open("_diag_out.txt", "w") as f:
    f.write(f"GET status: {r.status_code}\n")
    f.write(f"GET body: {r.text[:300]}\n\n")

# PUT
r = c.put("/api/settings", json={"vidu_api_key": "test123"})
with open("_diag_out.txt", "a") as f:
    f.write(f"PUT status: {r.status_code}\n")
    f.write(f"PUT body: {r.text[:300]}\n\n")

# PUT empty
r = c.put("/api/settings", json={})
with open("_diag_out.txt", "a") as f:
    f.write(f"PUT empty status: {r.status_code}\n")
    f.write(f"PUT empty body: {r.text[:300]}\n")
