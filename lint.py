#!/usr/bin/env python3
"""CS2 Dashboard Lint — Pre-merge validation."""
import json, sys, re, glob

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
    """检查**所有** HTML 页面的结构（2026-09-16 之前只查 index.html，
    导致 report.html 缺一个 } 的问题一直没被发现）。

    注意：内联 JS 的**语法**检查不在这里做 —— 朴素的括号计数会被
    JS 字符串里的括号误触发（曾误报 "Script () imbalance"），
    准确的检查在 tools/check_inline_js.mjs（node vm.Script 编译）。"""
    all_errors = []
    paths = sorted(glob.glob("*.html"))
    if not paths:
        raise ValueError("no .html files found")
    for path in paths:
        with open(path, encoding="utf-8") as f:
            content = f.read()

        # Duplicate IDs
        ids = re.findall(r'id="([^"]+)"', content)
        dup = [k for k, v in (lambda c: {i: c.count(i) for i in c})(ids).items() if v > 1]
        if dup:
            all_errors.append(f"{path}: Duplicate IDs: {dup}")

    if all_errors:
        raise ValueError("; ".join(all_errors[:5]) + (f" …共{len(all_errors)}条" if len(all_errors) > 5 else ""))

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
check("all *.html structure (duplicate IDs)", check_html)
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
