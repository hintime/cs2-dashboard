"""Steam库存导入工具 — 本地运行，绕过CORS"""
import json, sys, urllib.request

STEAMID = sys.argv[1] if len(sys.argv) > 1 else input('Steam ID64 或 个人资料链接: ')
# 提取 steamid
import re
m = re.search(r'profiles/(\d+)|id/([\w-]+)', STEAMID)
if m: STEAMID = m.group(1) or m.group(2)

url = f'https://steamcommunity.com/inventory/{STEAMID}/730/2?l=schinese&count=5000'
print(f'[STEAM] Fetching: {url}')
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
except Exception as e:
    print(f'[STEAM] 失败: {e}')
    print('提示: 需开 Steam++ 且库存公开')
    sys.exit(1)

if not data.get('success'): 
    print('[STEAM] 库存为空或非公开'); sys.exit(1)

# 解析
descs = {}
for d in data.get('descriptions', []):
    descs[d['classid']+'_'+d['instanceid']] = d.get('market_hash_name', '')

items = []
for a in data.get('assets', []):
    mhn = descs.get(a['classid']+'_'+a['instanceid']) or a.get('market_hash_name', '')
    if mhn:
        items.append({'market_hash': mhn, 'name': mhn.replace('\u2605','').replace('\u2122','').strip()})

print(f'[STEAM] 获取 {len(items)} 件饰品')
# 输出兼容导入格式的JSON
out = {'items': items, 'count': len(items)}
out_path = 'steam_inventory.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f'[STEAM] 已保存到 {out_path}')
print(f'\n复制以下内容粘贴到网站导入框:')
print(json.dumps(out, ensure_ascii=False))
