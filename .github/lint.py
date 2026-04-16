#!/usr/bin/env python3
"""CS2 Dashboard Lint - Pre-commit validation."""
import json, sys, re

errors = []
warnings = []

HTML = "index.html"
HOLDINGS = "holdings.json"
MARKET = "market.json"

def check(name, fn):
    try:
        fn()
        print("  [OK] " + name)
    except Exception as e:
        errors.append("[FAIL] " + name + ": " + str(e))
        print("  [FAIL] " + name + ": " + str(e))

# 1. JSON validity
def validate_json(path):
    with open(path, encoding="utf-8") as f:
        json.load(f)

# 2. HTML structural checks
def check_html_structure():
    with open(HTML, encoding="utf-8") as f:
        content = f.read()

    # 2a. No duplicate IDs
    ids = re.findall(r'id="([^"]+)"', content)
    seen = {}
    for i in ids:
        seen[i] = seen.get(i, 0) + 1
    dup = [k for k, v in seen.items() if v > 1]
    if dup:
        raise ValueError("Duplicate IDs: " + str(dup))

    # 2b. Modal HTML must appear BEFORE the final </script>
    script_end_pos = content.rfind("</script>")
    modal_pos = content.find('id="tokenModal"')
    if modal_pos > 0 and modal_pos > script_end_pos:
        raise ValueError("Modal HTML appears AFTER </script> - onclick handlers will fail!")

    # 2c. Critical elements must exist
    for rid in ["gearBtn", "tokenModal", "tokenSave"]:
        if 'id="' + rid + '"' not in content:
            raise ValueError("Missing required id=\"" + rid + "\"")

    # 2d. Balanced JS braces/brackets/parentheses in script blocks
    for m in re.finditer(r'<script>(.*?)</script>', content, re.DOTALL):
        src = m.group(1)
        for open_c, close_c in [("{", "}"), ("(", ")"), ("[", "]")]:
            if src.count(open_c) != src.count(close_c):
                raise ValueError(
                    "Script block: " + open_c + close_c + " imbalance: "
                    + open_c + "=" + str(src.count(open_c))
                    + ", " + close_c + "=" + str(src.count(close_c))
                )

# 3. holdings.json data sanity
def check_holdings():
    with open(HOLDINGS, encoding="utf-8") as f:
        d = json.load(f)
    items = d.get("items", [])
    if not items:
        raise ValueError(HOLDINGS + ": items list is empty")
    for item in items:
        if "cost" not in item or "price" not in item:
            raise ValueError("Item missing cost/price field: " + str(item.get("name", "?")))
        if item["cost"] < 0 or item["price"] < 0:
            raise ValueError("Item has negative cost/price: " + str(item.get("name", "?")))
        # qty should be >= 1
        qty = item.get("qty", 1)
        if not isinstance(qty, int) or qty < 1:
            raise ValueError("Item qty invalid: " + str(item.get("name", "?")))

# 4. market.json - only check fields actually used by the frontend
#    Frontend uses: index (ohlc/values/dates/latest/change/min/max),
#    items[name].latest, items[name].name_cn
#    Frontend does NOT use items[name].kline (stored but not rendered)
def check_market():
    with open(MARKET, encoding="utf-8") as f:
        d = json.load(f)

    # K-line check removed (K-line feature disabled)

    # Check items - only the fields actually used by the frontend
    items = d.get("items", {})
    if not items:
        warnings.append("market.json: 'items' is empty - no price data")
    for name, item in items.items():
        if item.get("latest") is None:
            warnings.append("market.json item '" + name + "': latest price is null")

print("Lint: cs2-dashboard")
check("holdings.json is valid JSON",       lambda: validate_json(HOLDINGS))
check("market.json is valid JSON",         lambda: validate_json(MARKET))
check("index.html structure",              check_html_structure)
check("holdings.json data sanity",         check_holdings)
check("market.json data sanity",          check_market)

if warnings:
    print("")
    print("Warnings:")
    for w in warnings:
        print("  " + w)

if errors:
    print("")
    print("ERRORS:")
    for e in errors:
        print("  " + e)
    sys.exit(1)
else:
    print("")
    print("All checks passed!")
    sys.exit(0)
