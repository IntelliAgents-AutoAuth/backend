import urllib.request
import json

url = "http://localhost:8000/api/v1/auth/login"
data = {
    "username": "sai@example.com",
    "password": "test123"
}

req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})

try:
    with urllib.request.urlopen(req) as f:
        print(f"Status: {f.getcode()}")
        print(f"Response: {f.read().decode()}")
except urllib.error.HTTPError as e:
    print(f"Status: {e.code}")
    print(f"Response: {e.read().decode()}")
except Exception as e:
    print(f"Error: {e}")
