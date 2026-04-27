"""
Probe Hyros /leads endpoint to see full field structure including
any achievement/conversion/tag events like the 'hubspot' achievement.
"""
import json, urllib.parse, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timedelta


def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def hyros_get(path, key, params=None):
    base = "https://api.hyros.com/v1/api/v1.0"
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"API-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": e.read().decode()[:500]}


env = load_env(Path(__file__).parent / ".env")
key = env["HYROS_API_KEY"]

today = datetime.now().strftime("%Y-%m-%d")
week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

print("=== Pulling 3 leads to inspect full field structure ===\n")
status, body = hyros_get("/leads", key, {"fromDate": week, "toDate": today, "pageSize": 3})
print(f"HTTP {status}")

results = body.get("result") or body.get("data") or []
print(f"Leads returned: {len(results)}\n")

for i, lead in enumerate(results):
    print(f"--- Lead {i+1} ---")
    print(json.dumps(lead, indent=2, default=str))
    print()

# Also check if there's a dedicated achievements or events endpoint
print("=== Probing related endpoints ===")
for path in ["/leads/achievements", "/leads/tags", "/leads/events", "/achievements", "/events", "/tags"]:
    s, b = hyros_get(path, key, {"fromDate": week, "toDate": today})
    print(f"{path}: HTTP {s} -> {list(b.keys()) if isinstance(b, dict) else str(b)[:100]}")
