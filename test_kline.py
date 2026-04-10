import requests
import json
import os

# Read API key from environment or file
api_key = os.environ.get('STEAMDT_KEY', '')
if not api_key:
    # Try to read from a local file
    try:
        with open('steamt_key.txt', 'r') as f:
            api_key = f.read().strip()
    except:
        pass

if not api_key:
    print("No STEAMDT_KEY found")
    exit(1)

base_url = "https://open.steamdt.com"

# Test K-line API
item_name = "AK-47 | Redline (Field-Tested)"
print(f"Testing K-line API for: {item_name}")

# Get single price first
resp = requests.get(
    f"{base_url}/open/cs2/v1/price/single",
    params={"marketHashName": item_name},
    headers={"Authorization": f"Bearer {api_key}"}
)
print("Price response:", resp.status_code)
price_data = resp.json()
print(json.dumps(price_data, indent=2, ensure_ascii=False)[:500])

# Get K-line data
resp = requests.post(
    f"{base_url}/open/cs2/v1/item/kline",
    json={
        "marketHashName": item_name,
        "type": 2,  # Daily K
        "platform": "BUFF"
    },
    headers={"Authorization": f"Bearer {api_key}"}
)
print("\nK-line response:", resp.status_code)
kline_data = resp.json()
print(json.dumps(kline_data, indent=2, ensure_ascii=False)[:1000])
