#!/usr/bin/env python3
"""CS2 Dashboard Lint — Pre-merge validation."""
import json, sys, re

errors = []
warnings = []

def check(name, fn):
    try:
        fn()
        print(f"  [OK] {name}")
    except Exception as e:
        errors.append(f"[FAIL] {name}: {e}")
        print(f"  [FAIL] {name}: {e}")

def validate_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def check_html():
    with open("index.html", encoding="utf-8") as f:
        content = f.read()

    # Duplicate IDs
    ids = re.findall(r'id="([^"]+)"', content)
    dup = [k for k, v in (lambda c: {i: c.count(i) for i in c})(ids).items() if v > 1]
    if dup:
        raise ValueError(f"Duplicate IDs: {dup}")

    # Critical elements
    for rid in ["gearBtn", "tokenModal", "tokenSave", "tbody"]:
        if f'id="{rid}"' not in content:
            raise ValueError(f'Missing #{rid}')

    # Brace balance in script blocks
    for m in re.finditer(r'<script>(.*?)</script>', content, re.DOTALL):
        src = m.group(1)
        for o, c in [("{", "}"), ("(", ")"), ("[", "]")]:
            if src.count(o) != src.count(c):
                raise ValueError(f"Script {o}{c} imbalance: {o}={src.count(o)} {c}={src.count(c)}")

def check_holdings():
    d = validate_json("holdings.json")
    items = d.get("items", [])
    if not items:
        raise ValueError("items list is empty")
    for item in items:
        name = item.get("name", "?")
        if "cost" not in item:
            raise ValueError(f"Missing cost: {name}")
        if "price" not in item:
            raise ValueError(f"Missing price: {name}")
        if item["cost"] < 0:
            raise ValueError(f"Negative cost: {name}")
        if not item.get("market_hash"):
            warnings.append(f"No market_hash: {name}")

def check_market():
    d = validate_json("market.json")
    if not d.get("alerts"):
        warnings.append("market.json: no alerts data")

print("Lint: cs2-dashboard")
check("holdings.json valid", lambda: validate_json("holdings.json"))
check("market.json valid", lambda: validate_json("market.json"))
check("index.html structure", check_html)
check("holdings.json data", check_holdings)
check("market.json data", check_market)

if warnings:
    print("\nWarnings:")
    for w in warnings:
        print(f"  {w}")

if errors:
    print("\nERRORS:")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)

print("\nAll checks passed!")
