import json
with open('holdings.json', 'r', encoding='utf-8') as f:
    h = json.load(f)
items = h['items']
for it in sorted(items, key=lambda x: x.get('cost',0)*x.get('qty',1), reverse=True)[:10]:
    ct = it['cost'] * it['qty']
    pt = it['price'] * it['qty']
    name = it['name']
    print(f'{name:40s} qty={it["qty"]} cost={it["cost"]:8.2f} price={it["price"]:8.2f} cost_t={ct:8.2f} price_t={pt:8.2f}')
print(f'Total cost: {h["total_cost"]}  Total market: {h["total_market"]}')
