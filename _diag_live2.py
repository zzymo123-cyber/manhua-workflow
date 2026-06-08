import http.client, json, socket

# Try multiple connection methods
results = []

# Method 1: localhost
try:
    conn = http.client.HTTPConnection("localhost", 8000, timeout=5)
    conn.request("GET", "/api/settings")
    r = conn.getresponse()
    results.append(f"localhost: GET status={r.status} body={r.read().decode()[:100]}")
    conn.close()
except Exception as e:
    results.append(f"localhost: ERROR {e}")

# Method 2: 127.0.0.1
try:
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=5)
    conn.request("GET", "/api/settings")
    r = conn.getresponse()
    results.append(f"127.0.0.1: GET status={r.status} body={r.read().decode()[:100]}")
    conn.close()
except Exception as e:
    results.append(f"127.0.0.1: ERROR {e}")

# Method 3: check what's actually on port 8000
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(("127.0.0.1", 8000))
    s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
    data = s.recv(4096)
    results.append(f"raw socket: {data[:200].decode('utf-8', errors='replace')}")
    s.close()
except Exception as e:
    results.append(f"raw socket: ERROR {e}")

with open("_diag_live2.txt", "w") as f:
    f.write("\n".join(results))
