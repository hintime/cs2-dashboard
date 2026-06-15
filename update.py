#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 Dashboard 数据更新脚本 (优化版)
- ECOSteam API 获取持仓价格 → holdings.json
- BUFF 价格历史自算异动 → market.json (alerts)
- 可选：SteamDT K-lines (需有效 API Key)

优化：
- 并发请求（concurrent.futures）
- 数据缓存复用（alerts + recommendations 共享）
- 批量处理
"""
import json, time, base64, urllib.request, urllib.error, urllib.parse, subprocess, os, sys, ssl, gzip, socket, shutil

# ── 计划任务 GBK 兼容：强制 UTF-8 ──
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'reconfigure') else None
sys.stderr.reconfigure(encoding='utf-8', errors='replace') if hasattr(sys.stderr, 'reconfigure') else None
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eco_sign import get_eco_key, sign_eco
import steam_market as sm
import eco_catalog
import recommend  # CSQAQ multi-platform price provider

# ═══════════════ CONFIG ═══════════════
PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
# CSQAQ removed — alerts now self-computed from BUFF price history
STEAM_KEY = os.environ.get('STEAMDT_KEY', '')
GH_TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', 'sk-3a9f8fed7ff94e7398e3a9164807cb24')
ZHIPU_KEY = os.environ.get('ZHIPU_KEY', '981fb5b064af4d86896d804ddea2acbc.VmZsKxfM4fL4vefz')
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'deepseek')  # 'deepseek' or 'zhipu'
REPO = 'hintime/cs2-dashboard'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..') if SCRIPT_DIR.endswith('.github') else SCRIPT_DIR

MAX_RETRIES = 3
RETRY_DELAY = 2

# ═══════════════ AI Provider 统一调度 ═══════════════
def _ai_key():
    """返回当前 provider 的 API key"""
    return DEEPSEEK_KEY if AI_PROVIDER == 'deepseek' else ZHIPU_KEY

def _ai_endpoint():
    """返回当前 provider 的 API endpoint"""
    return 'https://open.bigmodel.cn/api/paas/v4/chat/completions' if AI_PROVIDER == 'deepseek' \
        else 'https://open.bigmodel.cn/api/paas/v4/chat/completions'

def _ai_model():
    """返回当前 provider 的模型名"""
    return 'glm-4-flash' if AI_PROVIDER == 'deepseek' else 'glm-4-flash'

def _ai_call(messages, max_tokens=2048, temperature=0.5, json_mode=False, tools=None, timeout=90):
    """统一 AI 调用 — 自动切换 DeepSeek/Zhipu"""
    key = _ai_key()
    if not key:
        print(f'[AI] No key for {AI_PROVIDER}, skip')
        return None
    
    body = {
        'model': _ai_model(),
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature
    }
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    if tools:
        body['tools'] = tools
    
    for attempt in range(3):
        try:
            data = json.dumps(body).encode('utf-8')
            req = urllib.request.Request(_ai_endpoint(), data=data, headers={
                'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'
            })
            resp = urllib.request.urlopen(req, timeout=timeout)
            result = json.loads(resp.read().decode('utf-8'))
            return result['choices'][0]['message'].get('content', '')
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = (attempt + 1) * 10
                print(f'[AI] {AI_PROVIDER} 429 rate limited, waiting {wait}s...')
                time.sleep(wait)
            else:
                print(f'[AI] {AI_PROVIDER} HTTP {e.code}: {e}', file=sys.stderr)
                if attempt == 2: return None
                time.sleep(3)
        except Exception as e:
            print(f'[AI] {AI_PROVIDER} failed (attempt {attempt+1}): {e}', file=sys.stderr)
            if attempt == 2: return None
            time.sleep(3)
    return None

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ═══════════════ JSON 完整性自动修复 ═══════════════
def _fix_corrupted_jsons():
    """扫描所有 JSON 文件，自动修复 git 冲突标记"""
    import shutil
    fixed = 0
    for filename in os.listdir(DATA_DIR):
        if not filename.endswith('.json'): continue
        path = os.path.join(DATA_DIR, filename)
        if os.path.getsize(path) < 5: continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            # 检测冲突标记
            if '<<<<<<<' in content and '=======' in content and '>>>>>>>' in content:
                try:
                    # 1. 先尝试从 git HEAD 恢复
                    result = subprocess.run(
                        ['git', 'checkout', 'HEAD', '--', filename],
                        capture_output=True, text=True, cwd=DATA_DIR, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if result.returncode == 0:
                        print(f'[FIX] {filename}: restored from git')
                        fixed += 1
                        continue
                except: pass
                # 2. git 恢复失败，手动取 HEAD 版本内容
                try:
                    head = content.split('>>>>>>>')[0].split('=======')[0].replace('<<<<<<< HEAD', '')
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(head.strip())
                    json.loads(head.strip())  # 验证
                    print(f'[FIX] {filename}: resolved conflict (HEAD)')
                    fixed += 1
                except Exception as e:
                    print(f'[FIX] {filename}: FAILED: {e}', file=sys.stderr)
            else:
                # 无冲突标记但 JSON 损坏？验证并尝试修复截断
                try:
                    json.loads(content)
                except json.JSONDecodeError as e:
                    # 检查是否截断（错误位置在文件末尾附近）
                    stripped = content.rstrip()
                    if e.pos >= len(stripped) - 200:
                        try:
                            before = content[:e.pos]
                            open_b = before.count('{') - before.count('}')
                            open_a = before.count('[') - before.count(']')
                            repaired = stripped
                            if repaired.endswith(','):
                                repaired = repaired[:-1].rstrip()
                            repaired += '\n' + '  ' * open_a + ']' * open_a + '}' * open_b
                            json.loads(repaired)  # 验证
                            # 备份原文件
                            backup = path + '.broken'
                            shutil.copy2(path, backup)
                            with open(path, 'w', encoding='utf-8') as f:
                                f.write(repaired)
                            print(f'[FIX] {filename}: truncated JSON repaired (+{open_a}]+{open_b}}})')
                            fixed += 1
                        except Exception as e2:
                            print(f'[WARN] {filename}: JSON corrupt but not truncation: {e2}', file=sys.stderr)
                    else:
                        print(f'[WARN] {filename}: JSON parse error at pos {e.pos}/{len(stripped)}: {e.msg}', file=sys.stderr)
        except Exception:
            pass
    if fixed:
        print(f'[FIX] Auto-repaired {fixed} corrupted JSONs')
    return fixed
# Track which files were modified
dirty_files = set()

# ═══════════════ HOSTS BYPASS ═══════════════
# Steam++ injects hosts entries pointing api.steampowered.com → 127.0.0.1
# We detect this and skip those requests fast instead of waiting 30s timeout
HOSTS_BLOCKED = set()  # cached blocked hosts

def _check_host_blocked(host):
    """Return True if host is redirected to 127.0.0.1 by hosts file."""
    if host in HOSTS_BLOCKED:
        return True
    try:
        ip = socket.gethostbyname(host)
        if ip == '127.0.0.1':
            HOSTS_BLOCKED.add(host)
            print(f'[HOSTS] {host} blocked by hosts file (127.0.0.1), skipping')
            return True
    except Exception:
        pass
    return False

# ═══════════════ HTTP HELPERS ═══════════════
def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode('utf-8'))
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)

def http_post(url, body, headers=None, timeout=15):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if isinstance(body, (dict, list)) else body
    hdrs = {'Content-Type': 'application/json'}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method='POST')
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode('utf-8'))
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)

def http_post_raw(url, body, headers=None, timeout=15):
    """Return parsed JSON, auto-detecting encoding (UTF-8/GBK/Latin-1)"""
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if isinstance(body, (dict, list)) else body
    hdrs = {'Content-Type': 'application/json'}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method='POST')
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                for enc in ('utf-8', 'gbk', 'latin-1'):
                    try:
                        return json.loads(raw.decode(enc))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                return {}
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)

# ═══════════════ ECO PRICES (并发) ═══════════════
def fetch_eco_prices(hash_names):
    """Batch fetch ECO prices → {HashName: price_float} (并发)"""
    prices = {}
    batch_size = 100
    batches = [hash_names[i:i+batch_size] for i in range(0, len(hash_names), batch_size)]
    
    def fetch_batch(batch, idx):
        params = {
            'PartnerId': PARTNER_ID,
            'Timestamp': str(int(time.time())),
            'GameID': '730',
            'HashName': batch
        }
        params['Sign'] = sign_eco(params)
        try:
            result = http_post(
                'https://openapi.ecosteam.cn/Api/Market/BatchSearchSellingPrice',
                params, timeout=30
            )
            batch_prices = {}
            if str(result.get('ResultCode')) == '0':
                for item in (result.get('ResultData') or []):
                    hn = item.get('HashName')
                    raw = item.get('MarketComprePrice') or item.get('MinPrice') or item.get('Price') or '0'
                    try:
                        p = float(raw)
                    except (ValueError, TypeError):
                        p = 0.0
                    if hn and p > 0:
                        batch_prices[hn] = p
            return batch_prices
        except Exception as e:
            print(f'[ERROR] ECO batch {idx}: {e}', file=sys.stderr)
            return {}
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_batch, batch, i): i for i, batch in enumerate(batches)}
        for future in as_completed(futures):
            prices.update(future.result())
    
    return prices

# ═══════════════ 排除规则（不感兴趣的饰品类型） ═══════════════
_EXCLUDE_PREFIXES = ('StatTrak™ ', 'StatTrak ', 'Souvenir ')
_EXCLUDE_EXTERIORS = {'破损不堪', '战痕累累'}

def _filter_excluded(items):
    """排除 StatTrak / Souvenir(纪念品) / 破损不堪(BS) / 战痕累累(WW) 饰品"""
    return [i for i in items
            if not any(i.get('name','').startswith(p) for p in _EXCLUDE_PREFIXES)
            and i.get('exterior','') not in _EXCLUDE_EXTERIORS]

# ═══════════════ BUFF PRICE HISTORY & ALERTS (自计算) ═══════════════
_buff_history_cache = None

def load_buff_history():
    """Load BUFF price history from disk"""
    global _buff_history_cache
    if _buff_history_cache is not None:
        return _buff_history_cache
    history_file = os.path.join(DATA_DIR, 'buff_history.json')
    if os.path.exists(history_file):
        try:
            _buff_history_cache = read_json(history_file)
            return _buff_history_cache
        except:
            pass
    return {}

def save_buff_history(steamdt_prices):
    """Save hourly + daily BUFF/悠悠 snapshots to buff_history.json"""
    hour_key = time.strftime('%Y-%m-%dT%H:00')  # 小时级（异动）
    day_key = time.strftime('%Y-%m-%d')          # 日级（7日涨跌）
    history_file = os.path.join(DATA_DIR, 'buff_history.json')
    
    history = load_buff_history()
    
    # Keep last 48 hours + 15 days
    dates = sorted(history.keys(), reverse=True)
    keep = []
    for d in dates:
        if len(d) == 16 and len(keep) < 48:  # hourly: YYYY-MM-DDTHH:MM
            keep.append(d)
        elif len(d) == 10 and len(keep) < 48+15:  # daily: YYYY-MM-DD
            keep.append(d)
    for old_date in dates:
        if old_date not in keep:
            del history[old_date]
    
    # Save snapshot (BUFF + 悠悠) — both hourly and daily
    history[hour_key] = {}
    history[day_key] = {}
    for name, info in steamdt_prices.items():
        if isinstance(info, dict):
            entry = {
                'buff_sell': info.get('buff_sell', 0),
                'buff_buy': info.get('buff_buy', 0),
                'buff_sell_num': info.get('buff_sell_num', 0),
                'buff_buy_num': info.get('buff_buy_num', 0),
                'yyyp_sell': info.get('yyyp_sell', 0),
                'yyyp_sell_num': info.get('yyyp_sell_num', 0),
            }
            # 也从 platforms 取悠悠数据
            plats = info.get('platforms', {})
            if plats:
                yyyp = plats.get('yyyp', {})
                if yyyp:
                    if not entry['yyyp_sell']:
                        entry['yyyp_sell'] = yyyp.get('price', 0) or yyyp.get('sell_price', 0) or 0
                    if not entry['yyyp_sell_num']:
                        entry['yyyp_sell_num'] = yyyp.get('sell_num', 0) or yyyp.get('count', 0) or 0
            history[hour_key][name] = entry
            history[day_key][name] = entry
    
    write_json(history_file, history)
    _buff_history_cache = history
    y_c = sum(1 for v in history[hour_key].values() if v.get('yyyp_sell', 0) > 0)
    print(f'[HISTORY] Hour {hour_key} + Day {day_key}: {len(steamdt_prices)} items, {y_c} with 悠悠')
    return history

def compute_alerts(steamdt_prices):
    """Compute price change alerts from BUFF price history (replaces CSQAQ)
    
    Returns: list of alert dicts with name, price, rate_1, rate_7, etc.
    """
    # Lazy-load price_summary for fallback
    _ph_summary = None
    def _get_ph_summary(name):
        nonlocal _ph_summary
        if _ph_summary is None:
            ps_file = os.path.join(DATA_DIR, 'price_summary.json')
            if os.path.exists(ps_file):
                _ph_summary = read_json(ps_file) or {}
            else:
                _ph_summary = {}
        return _ph_summary.get(name, {})
    
    history = load_buff_history()
    if not history:
        print('[ALERTS] No history available, returning empty list')
        return []
    if not steamdt_prices:
        print('[ALERTS] No current prices, returning empty list')
        return []
    
    dates = sorted(history.keys())
    today = time.strftime('%Y-%m-%d')
    target_1d = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400))
    target_7d = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400 * 7))
    
    # Find closest dates to 1d and 7d ago
    yest = None
    week = None
    for d in reversed(dates):
        if d < today:
            if yest is None:
                yest = d
            if d <= target_7d and week is None:
                week = d
    if yest is None and len(dates) >= 2:
        yest = dates[-2]
    if week is None and len(dates) >= 7:
        week = dates[-7]
    
    if yest:
        print(f'[ALERTS] Using {yest} as 1d reference (target={target_1d})')
    if week:
        print(f'[ALERTS] Using {week} as 7d reference (target={target_7d})')
    
    alerts = []
    for name, info in steamdt_prices.items():
        if not isinstance(info, dict):
            continue
        current = info.get('buff_sell', 0)
        if current <= 0:
            continue
        
        prev_price = 0
        if yest and yest in history:
            prev = history[yest].get(name, {})
            if isinstance(prev, dict):
                prev_price = prev.get('buff_sell', 0)
        
        old_price = 0
        if week and week in history:
            old = history[week].get(name, {})
            if isinstance(old, dict):
                old_price = old.get('buff_sell', 0)
        
        rate_1 = round((current - prev_price) / prev_price * 100, 2) if prev_price > 0 else 0
        rate_7 = round((current - old_price) / old_price * 100, 2) if old_price > 0 else 0
        
        # Fallback: 如果 SteamDT 历史不足，从 price_summary.json 补
        if rate_7 == 0 or rate_1 == 0:
            ph = _get_ph_summary(name)
            if ph:
                if rate_7 == 0 and ph.get('change_7d'):
                    rate_7 = round(ph['change_7d'], 2)
                if rate_1 == 0 and ph.get('change_1d'):
                    rate_1 = round(ph['change_1d'], 2)
        
        alerts.append({
            'name': name,
            'price': current,
            'rate_1': rate_1,
            'rate_7': rate_7,
            'buff_sell': info.get('buff_sell_num', 0),
            'buff_buy': info.get('buff_buy_num', 0),
            'buff_price': current,
            'steam_buy': 0,
            'img': '',
        })
    
    # Sort by absolute rate_1 (biggest changers first)
    alerts.sort(key=lambda x: abs(x.get('rate_1', 0)), reverse=True)
    print(f'[ALERTS] Computed {len(alerts)} items from history ({len(dates)} days)')
    return alerts

# ═══════════════ RECOMMENDATIONS (复用缓存) ═══════════════
_cached_eco_full = None

def fetch_eco_full():
    """Fetch full ECO price list (36k+ items) - 带缓存"""
    global _cached_eco_full
    if _cached_eco_full is not None:
        return _cached_eco_full
    
    params = {
        'PartnerId': PARTNER_ID,
        'Timestamp': str(int(time.time())),
        'GameID': '730',
    }
    params['Sign'] = sign_eco(params)
    result = http_post('https://openapi.ecosteam.cn/Api/Market/GetHashNameAndPriceList', params, timeout=60)
    if str(result.get('ResultCode')) != '0':
        raise Exception(f"ECO ResultCode={result.get('ResultCode')}")
    _cached_eco_full = result.get('ResultData') or []
    return _cached_eco_full

def generate_recommendations(alerts=None, steamdt_prices=None):
    """Dual-scoring recommendation engine.
    ECO score (0-100): supply/demand + valuation from eco_tracked.json
    BUFF score (0-100): price premium + order book from SteamDT data
    Combined: max(ECO_score, BUFF_score), top 30, threshold >= 25
    Returns: {'all': list of sorted recommendations}
    """
    # Load ECO tracked items (built by eco_catalog.py)
    tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
    if not os.path.exists(tracked_path):
        print('[REC] eco_tracked.json not found, no recommendations')
        return {'all': []}

    with open(tracked_path, 'r', encoding='utf-8') as f:
        tracked = json.load(f)
    print(f'[REC] Loaded {len(tracked)} items from eco_tracked.json')

    # 排除 StatTrak / Souvenir(纪念品) / BS(破损不堪/战痕累累) 等不想要的
    _EXCLUDE_PREFIXES = ('StatTrak™ ', 'StatTrak ', 'Souvenir ')
    _EXCLUDE_EXTERIORS = ('Battle-Scarred', '战痕累累', '破损不堪')
    before = len(tracked)
    tracked = [i for i in tracked
               if not any(i.get('HashName','').startswith(p) for p in _EXCLUDE_PREFIXES)
               and not any(e in (i.get('HashName','') + i.get('GoodsName','')) for e in _EXCLUDE_EXTERIORS)]
    if len(tracked) < before:
        print(f'[REC] Filtered out {before - len(tracked)} excluded items ({len(tracked)} remaining)')

    # Build BUFF price lookup from steamdt_prices (32 holdings + enriched catalog)
    buff_map = {}
    if steamdt_prices:
        buff_map = steamdt_prices
    # Also check items that have BUFF data in eco_tracked.json (ENRICH_BUFF=1)
    for item in tracked:
        hn = item.get('HashName', '')
        if hn not in buff_map and item.get('buff_sell', 0) > 0:
            buff_map[hn] = {
                'buff_sell': item.get('buff_sell', 0),
                'buff_buy': item.get('buff_buy', 0),
                'buff_sell_num': item.get('buff_sell_num', 0),
                'buff_buy_num': item.get('buff_buy_num', 0),
            }
    print(f'[REC] BUFF prices available for {len(buff_map)} items')

    all_recs = []

    for item in tracked:
        hn = item.get('HashName', '')
        gn = item.get('GoodsName', hn)
        price = float(item.get('Price') or 0)
        compre = float(item.get('MarketComprePrice') or 0)
        selling = int(item.get('SellingTotal') or 0)
        qg_total = int(item.get('QGTotal') or 0)
        qg_max = float(item.get('QGMaxPrice') or 0)

        if price < 20:  # Skip items below ¥20 (filter cheap stickers/graffiti)
            continue

        # ══════════ ECO Score (0-100): supply/demand + valuation ══════════
        eco_score = 0.0
        eco_reasons = []

        # 1. Undervaluation: MarketComprePrice >> Price (35 pts max)
        if compre > 0 and price > 0:
            underval_pct = (compre - price) / price * 100
            if underval_pct > 5:  # Require >5% gap
                uv = min(underval_pct * 0.7, 35)
                eco_score += uv
                if uv > 7:
                    eco_reasons.append('ECO低估{}% (综合{:.0f} vs 现价{:.0f})'.format(
                        round(underval_pct), compre, price))

        # 2. Scarcity: buy/sell ratio (20 pts max, logarithmic to prevent domination by stickers)
        if selling > 0 and qg_total > 0:
            import math
            ratio = qg_total / selling
            if ratio > 0.05:
                sc = min(math.log(ratio + 1) * 10, 20)
                eco_score += sc
                if sc > 5:
                    eco_reasons.append('稀缺求/售比{:.0%} (求{} 售{})'.format(ratio, qg_total, selling))

        # 3. Demand strength: buy price vs sell price (15 pts max)
        if qg_max > 0 and price > 0:
            demand = qg_max / price
            if demand > 0.5:
                dm = min(demand * 15, 15)
                eco_score += dm
                if dm > 5:
                    eco_reasons.append('求购活跃 出价{:.0f} vs 售价{:.0f}'.format(qg_max, price))

        # ══════════ BUFF Score (0-100): price premium + order book ══════════
        buff_score = 0.0
        buff_reasons = []
        bd = buff_map.get(hn, {})
        if bd:
            bs = bd.get('buff_sell', 0) or 0
            bb = bd.get('buff_buy', 0) or 0
            bsn = bd.get('buff_sell_num', 0) or 0
            bbn = bd.get('buff_buy_num', 0) or 0

            # 1. BUFF premium over ECO price (30 pts max)
            if bs > 0 and price > 0:
                premium = (bs - price) / price * 100
                if premium > 3:
                    pr = min(premium * 0.7, 30)
                    buff_score += pr
                    if pr > 7:
                        buff_reasons.append('BUFF溢价{}% ({:.0f} vs ECO{:.0f})'.format(
                            round(premium), bs, price))

            # 2. BUFF buy/sell ratio (15 pts max)
            if bsn > 0 and bbn > 0:
                b_ratio = bbn / bsn
                if b_ratio > 0.05:
                    br = min(b_ratio * 15, 15)
                    buff_score += br
                    if br > 5:
                        buff_reasons.append('BUFF买/卖比{:.0%} (买{} 卖{})'.format(b_ratio, bbn, bsn))

            # 3. BUFF liquidity depth (10 pts max)
            if bsn > 0:
                liq = min(bsn / 500 * 10, 10)
                buff_score += liq

            # 4. BUFF buy power (bonus 5 pts)
            if bsn > 0 and bbn > 0:
                bp = min(bbn / (bsn + bbn) * 5, 5)
                buff_score += bp

        # ══════════ 悠悠有品 Score (bonus, 20 pts max) ══════════
        yyyp_sell = item.get('yyyp_sell', 0) or 0
        yyyp_sell_num = item.get('yyyp_sell_num', 0) or 0
        # 悠悠在售少于40件 → 不推荐
        if yyyp_sell_num > 0 and yyyp_sell_num < 40:
            continue
        if yyyp_sell > 0:
            # 5. 悠悠价格 vs ECO价格 (10 pts max)
            yyyp_premium = (yyyp_sell - price) / price * 100 if price > 0 else 0
            if yyyp_premium > 2:
                yp = min(yyyp_premium * 0.5, 10)
                buff_score += yp
                if yp > 4:
                    buff_reasons.append('悠悠溢价{}% ({:.0f} vs ECO{:.0f})'.format(
                        round(yyyp_premium, 1), yyyp_sell, price))

            # 6. 悠悠在售深度 (10 pts max) — 在售少说明稀缺
            if yyyp_sell_num > 0:
                scarce = min(max(0, (500 - yyyp_sell_num) / 500 * 10), 10)
                if scarce > 2:
                    buff_score += scarce
                    if scarce > 5:
                        buff_reasons.append('悠悠在售仅{}件'.format(yyyp_sell_num))

        # ══════════ Combined ══════════
        # 应用AI追踪教训的评分权重调整
        eco_mult, buff_mult = _get_scoring_weights_from_lessons()
        final_score = max(eco_score * eco_mult, buff_score * buff_mult)

        if final_score < 25:
            continue

        # Primary source determines category tag and reason
        if buff_score > eco_score and buff_reasons:
            tag = 'buff'
            tag_label = '多平台信号'
            signal_desc = '多平台热度高'
            primary_reasons = buff_reasons + eco_reasons[:1]
        else:
            tag = 'eco'
            tag_label = 'ECO信号'
            signal_desc = 'ECO供需失衡'
            primary_reasons = eco_reasons + buff_reasons[:1]

        # ── Build rich actionable reason ──
        combined_reason = ' | '.join(primary_reasons[:3]) if primary_reasons else ''
        
        # ── 注入追踪教训信号（反哺推荐理由）──
        lesson_signal = ''
        reason_enhance = _get_reason_enhancements()  # 从追踪分析获取理由优化建议
        
        if tag == 'eco':
            # 教训: ECO信号溢价低/负→容易失败，需标注风险
            if buff_score < 5 or (bs > 0 and price > 0 and (bs - price) / price * 100 < 3):
                lesson_signal = ' ⚠溢价不足·待观察'
            elif eco_score > 30:
                lesson_signal = ' 供需位高·但需关注溢价'
        elif tag == 'buff':
            # 教训: 多平台信号+高溢价→成功率更高
            if bs > 0 and price > 0:
                premium = (bs - price) / price * 100
                if premium > 15:
                    lesson_signal = ' ✓溢价强劲·AI优选'
                elif premium > 5:
                    lesson_signal = ' 溢价适中·可考虑'
        
        # Apply lesson signals to tag
        display_tag = tag_label + lesson_signal
        
        # Build operation advice
        if tag == 'eco':
            # ECO signal: suggest buying at bid price
            suggest_bid = int(qg_max) if qg_max > 0 else int(price * 0.9)
            buy_advice_parts = []
            if selling > 0 and qg_total > 0:
                ratio = qg_total / selling
                if ratio > 3:
                    buy_advice_parts.append('需求旺盛，建议挂求购价¥{}买入'.format(suggest_bid))
                elif ratio > 1:
                    buy_advice_parts.append('供需偏紧，可挂求购价¥{}建仓'.format(suggest_bid))
                else:
                    buy_advice_parts.append('供需平衡，建议分批挂单买入')
            if compre > price:
                underval_pct = (compre - price) / price * 100
                if underval_pct > 10:
                    buy_advice_parts.append('综合评估价¥{:.0f}明显高于现价，性价比较高'.format(compre))
            if not buy_advice_parts:
                buy_advice_parts.append('建议分仓操作，单品种不超过10%仓位')
            # 教训反哺：ECO信号若无溢价支撑，标注风险
            if tag == 'eco' and buff_score < 5:
                buy_advice_parts.append('⚠ 纯ECO信号·缺乏多平台溢价验证')
            buy_advice = ' | '.join(buy_advice_parts[:2])
        else:
            # BUFF/multi-platform signal (T+7 market, no arbitrage possible)
            buy_advice_parts = []
            if bs > 0 and price > 0:
                diff = (bs - price) / price * 100
                if diff > 5:
                    buy_advice_parts.append('多平台溢价{:.1f}%，市场热度较高'.format(abs(diff)))
                elif diff < -5:
                    buy_advice_parts.append('多平台折价{:.1f}%，ECO价格偏高需谨慎'.format(abs(diff)))
                else:
                    buy_advice_parts.append('多平台与ECO价差{:.1f}%，价格趋近合理'.format(abs(diff)))
            if bsn > 0:
                buy_advice_parts.append('多平台在售{}件，流动性{}'.format(bsn, '充裕' if bsn > 100 else '一般'))
            if not buy_advice_parts:
                buy_advice_parts.append('建议结合ECO供需数据综合判断')
            buy_advice = ' | '.join(buy_advice_parts[:2])

        reason = '{} | ECO分{:.0f}/BUFF分{:.0f}→综合{:.0f} | {} | 💡 {} | 建议分仓操作,单品<10%{}'.format(
            display_tag, eco_score, buff_score, final_score, combined_reason, buy_advice, lesson_signal.replace(' ✓', ''))
        
        # 理由增强：根据追踪教训追加优化提示
        if reason_enhance:
            if reason_enhance.get('use') and reason_enhance['use'] not in combined_reason:
                pass  # 留作未来扩展
            if reason_enhance.get('wrong'):
                reason += ' | [AI建议] ' + reason_enhance['wrong'][:40]

        all_recs.append({
            'name': gn,
            'hash_name': hn,
            'price': price,
            'eco_score': round(eco_score, 1),
            'buff_score': round(buff_score, 1),
            'score': round(final_score, 1),
            'tag': tag,
            'tag_label': display_tag,
            'eco_price': price,
            'eco_compre': compre,
            'eco_selling': selling,
            'eco_qg_total': qg_total,
            'eco_qg_price': qg_max,
            'buff_sell': bd.get('buff_sell', 0) or 0,
            'buff_buy': bd.get('buff_buy', 0) or 0,
            'buff_sell_num': bd.get('buff_sell_num', 0) or 0,
            'buff_buy_num': bd.get('buff_buy_num', 0) or 0,
            'platforms': bd.get('platforms', {}),
            'yyyp_sell': item.get('yyyp_sell', 0) or 0,
            'yyyp_sell_num': item.get('yyyp_sell_num', 0) or 0,
            '_reason': reason,
            '_cat': tag,
        })

    # Sort by combined score, take top 30
    all_recs.sort(key=lambda x: x['score'], reverse=True)
    all_recs = all_recs[:30]

    eco_count = sum(1 for r in all_recs if r['tag'] == 'eco')
    buff_count = sum(1 for r in all_recs if r['tag'] == 'buff')
    print(f'[REC] {len(all_recs)} recommendations (ECO={eco_count}, BUFF={buff_count})')

    return {'all': all_recs}

# ═══════════════ STEAMDT K-LINES (optional) ═══════════════
def fetch_steamdt_klines(items_list):
    """Fetch K-line data from SteamDT if API key is valid"""
    if not STEAM_KEY or STEAM_KEY == 'test_key':
        print('[INFO] SteamDT key not configured, skipping K-lines')
        return {}

    try:
        # Test API key with a simple endpoint
        test = http_get(
            'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName=AK-47%20%7C%20Redline%20(Field-Tested)',
            headers={'Authorization': f'Bearer {STEAM_KEY}'}
        )
        print(f'[SteamDT] Test response: success={test.get("success")}, errorCode={test.get("errorCode")}, errorMsg={test.get("errorMsg")}')
        if not test.get('success'):
            print(f'[WARN] SteamDT key invalid (code={test.get("errorCode")}, msg={test.get("errorMsg")}), skipping')
            return {}
    except Exception as e:
        print(f'[WARN] SteamDT unreachable: {e}, skipping')
        return {}

    kline_data = {}
    for item in items_list:
        name = item.get('name_en') or item.get('name', '')
        try:
            resp = http_post(
                'https://open.steamdt.com/open/cs2/item/v1/kline',
                {'marketHashName': name, 'type': 2, 'platform': 'BUFF'},
                headers={'Authorization': f'Bearer {STEAM_KEY}'},
                timeout=20
            )
            if not resp.get('success'):
                print(f'  K-line API error for {name[:35]}: {resp.get("errorCode")} - {resp.get("errorMsg")}')
                continue
            if resp.get('data'):
                raw = resp['data']
                if isinstance(raw, dict):
                    keys = sorted(raw.keys(), key=lambda x: int(x) if x.isdigit() else x)
                    raw = [raw[k] for k in keys]
                parsed = []
                for p in raw:
                    if isinstance(p, (list, tuple)) and len(p) >= 5:
                        # SteamDT: [ts, open, close, high, low] → [ts, open, high, low, close, vol]
                        parsed.append([int(p[0]), float(p[1]), float(p[3]), float(p[4]), float(p[2]), 0])
                if parsed:
                    kline_data[name] = parsed
                    print(f'  K-line OK: {name[:35]} → {len(parsed)} pts')
        except Exception as e:
            print(f'  K-line ERR: {name[:35]}: {e}', file=sys.stderr)
        time.sleep(0.3)

    return kline_data

# ═══════════════ STEAMDT PRICES (BUFF/悠悠有品/C5/IGXE) ═══════════════
def fetch_steamdt_prices(hash_names, verbose=True):
    """Fetch multi-platform prices from SteamDT, respecting API limits:
    - single API: 60次/分钟 → 间隔≥1秒（用于持仓≤32件）
    - batch API: 1次/分钟 → 批量100件（用于全量追踪）
    
    策略：有BUFF价格的饰品跳过不查（增量更新）
    """
    if not STEAM_KEY or STEAM_KEY == 'test_key':
        if verbose:
            print('[INFO] SteamDT key not configured, skipping BUFF prices')
        return {}
    if not hash_names:
        return {}

    import urllib.parse as _up
    import json as _json

    def _parse_buff(name, resp):
        """Parse a single item's platform data from SteamDT response."""
        if not resp.get('success'):
            return None
        platforms = resp.get('data', [])
        if not platforms:
            return None
        priority = {'BUFF': 0, 'UUYP': 1, 'C5': 2, 'YOUPIN': 3, 'IGXE': 4, 'STEAM': 5}
        best, best_prio = None, 99
        for p_inner in platforms:
            plat = p_inner.get('platform', '')
            sell = float(p_inner.get('sellPrice', 0))
            buy = float(p_inner.get('biddingPrice', 0))
            if sell <= 0 and buy <= 0:
                continue
            prio = priority.get(plat.upper(), 50)
            if prio < best_prio:
                best_prio = prio
                best = {
                    'buff_sell': sell, 'buff_buy': buy,
                    'buff_sell_num': int(p_inner.get('sellCount', 0)),
                    'buff_buy_num': int(p_inner.get('biddingCount', 0)),
                    'update_time': p_inner.get('updateTime', 0),
                    'source': plat, 'buff_source': plat,
                }
                # 找到BUFF就是最优，其他平台不关我们事了
                if prio == 0:
                    break
        return best

    # ── 持仓（≤32件）：single API，间隔≥1秒 ──
    if len(hash_names) <= 32:
        prices = {}
        for i, name in enumerate(hash_names):
            try:
                time.sleep(1.0)  # 60次/分钟 → 1秒间隔
                url = f'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName={_up.quote(name)}'
                resp = http_get(url, headers={'Authorization': f'Bearer {STEAM_KEY}'}, timeout=15)
                data = _parse_buff(name, resp)
                if data:
                    prices[name] = data
                    if verbose and len(prices) <= 3:
                        print(f'  [SteamDT] {name[:40]}: {data["source"]} sell={data["buff_sell"]:.2f}')
            except Exception:
                pass
        if verbose:
            print(f'[SteamDT] Got {len(prices)}/{len(hash_names)} prices')
        return prices

    # ── 全量追踪：batch API，每分钟1次，每次100件 ──
    # 循环分批查询所有物品（每批100件，间隔65秒，遵守1次/分钟限制）
    # 每批完成立即合并到 eco_tracked.json，网络抖动不丢已查数据
    prices = {}
    total_batches = (len(hash_names) + 99) // 100
    # 自动模式下每批完成都写回 eco_tracked.json，不限批数
    eco_path = os.path.join(DATA_DIR, 'eco_tracked.json')
    try:
        for batch_idx in range(total_batches):
            start_i = batch_idx * 100
            batch = hash_names[start_i:start_i + 100]
            if not batch:
                break
            if verbose or batch_idx == 0:
                print(f'[SteamDT] Batch {batch_idx+1}/{total_batches}: {len(batch)} items...')
            if batch_idx > 0:
                time.sleep(65.0)  # 遵守1次/分钟限制（加5秒缓冲）
            body = _json.dumps({'marketHashNames': batch}).encode('utf-8')
            try:
                resp = http_post_raw(
                    'https://open.steamdt.com/open/cs2/v1/price/batch',
                    body,
                    headers={'Authorization': f'Bearer {STEAM_KEY}', 'Content-Type': 'application/json'},
                    timeout=30,
                )
                result = _json.loads(resp)
                batch_saved = 0
                if result.get('success'):
                    for item_data in result.get('data', []):
                        hn = item_data.get('marketHashName', '')
                        if hn and item_data.get('dataList'):
                            data = _parse_buff(hn, {'success': True, 'data': item_data['dataList']})
                            if data:
                                prices[hn] = data
                                batch_saved += 1
                # 每批完成后立即保存到 eco_tracked.json（防网络中断丢数据）
                if batch_saved > 0 and os.path.exists(eco_path):
                    try:
                        eco_items = read_json(eco_path)
                        if isinstance(eco_items, list):
                            for item in eco_items:
                                hn = item.get('HashName', '')
                                if hn in prices:
                                    bp = prices[hn]
                                    item['buff_sell'] = bp.get('buff_sell', 0)
                                    item['buff_buy'] = bp.get('buff_buy', 0)
                                    item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                    item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                                    item['buff_source'] = bp.get('buff_source', '')
                                    item['platforms'] = bp.get('platforms', {})
                            write_json(eco_path, eco_items)
                    except Exception as e2:
                        if verbose:
                            print(f'[SteamDT] eco_tracked save failed: {e2}', file=sys.stderr)
                if verbose:
                    print(f'[SteamDT] Batch {batch_idx+1}/{total_batches}: saved {batch_saved} prices, total accumulated {len(prices)}')
            except Exception as e:
                if verbose:
                    print(f'[SteamDT] Batch {batch_idx+1} failed (network): {e}', file=sys.stderr)
        if verbose:
            print(f'[SteamDT] Total from {len(hash_names)} items: {len(prices)} prices ({len(prices)/max(len(hash_names),1)*100:.1f}% coverage)')
    except Exception as e:
        if verbose:
            print(f'[SteamDT] Batch failed: {e}', file=sys.stderr)

    return prices

# ═══════════════ STEAM NEWS (fetch server-side, avoid CORS) ═══════════════
def fetch_steam_news():
    """Fetch CS2 Steam news → saves news.json (Chinese translated)"""
    try:
        if _check_host_blocked('api.steampowered.com'):
            print('[NEWS] Skipped (Steam API blocked by hosts file)')
            return None
        # Request Chinese localization from Steam API
        url = 'https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=730&count=12&maxlength=300&feeds=steam_community_announcements&l=schinese'
        r = http_get(url, timeout=8)
        raw = (r.get('appnews', {}) or {}).get('newsitems', [])
        if not raw:
            print('[NEWS] Empty response from Steam API')
            return None

        def strip_html(s):
            import re
            s = s.replace('{STEAM_CLAN_IMAGE}', '')
            s = re.sub(r'\{[A-Z_]+\}[^\s]*', '', s)  # {LINK_REMOVED} etc
            s = re.sub(r'\\[A-Za-z]+', '', s)          # \Cache \NIGHT \Fixed etc
            s = re.sub(r'https?://\S+', '', s)          # strip raw image URLs
            s = re.sub(r'<[^>]+>', '', s)
            s = s.replace('\n', ' ').replace('\r', ' ').strip()
            return s[:200]

        def has_cjk(s):
            return any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in s)

        def translate_text(text):
            """Translate EN→ZH via MyMemory API (fallback: Google Translate)"""
            if not text or has_cjk(text):
                return text
            # Try MyMemory first (free, no key, reliable in China)
            try:
                turl = 'https://api.mymemory.translated.net/get?q=' + urllib.parse.quote(text[:500]) + '&langpair=en|zh'
                resp = http_get(turl, timeout=20)
                if isinstance(resp, dict):
                    rd = resp.get('responseData', {})
                    translated = rd.get('translatedText', '')
                    match = rd.get('match', 0)
                    if translated and translated != text and match >= 0.5:
                        return translated
            except:
                pass
            # Fallback: Google Translate (may be blocked)
            try:
                turl = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=' + urllib.parse.quote(text[:200])
                resp = http_get(turl, timeout=20)
                if isinstance(resp, list) and len(resp) > 0 and isinstance(resp[0], list) and len(resp[0]) > 0:
                    translated = resp[0][0][0]
                    if translated and translated != text:
                        return translated
            except:
                pass
            return text

        # Chinese source labels
        LABEL_CN = {
            'Community Announcements': '社区公告',
            'Steam Community Announcements': 'Steam 社区公告',
            'Steam': 'Steam',
        }

        news_items = []
        for n in raw:
            title = n.get('title', '')
            body = strip_html(n.get('contents', ''))
            source = n.get('feedlabel', 'Steam')
            news_items.append({
                'title': translate_text(title),
                'body': translate_text(body),
                'url': n.get('url', 'https://steamcommunity.com/app/730/'),
                'date': n.get('date', 0),
                'source': LABEL_CN.get(source, source),
            })

        # Split: patches (update notes) vs general news
        patches = [x for x in news_items if '更新' in x['title'] or 'Update' in x['title'] or '更新' in x['title']]
        general = [x for x in news_items if x not in patches]

        result = {
            'news': general + patches,
            'updates': patches[:8],
            'updated': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f'[NEWS] Fetched {len(news_items)} items ({len(general)} news + {len(patches)} updates)')
        return result
    except Exception as e:
        print(f'[NEWS] Failed: {e}', file=sys.stderr)
        return None

# ═══════════════ FILE I/O (track dirty state) ═══════════════
def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(path, data):
    """原子写入 JSON：先写临时文件，再 rename，防止截断"""
    import tempfile
    dirname = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(suffix='.json', dir=dirname)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.name == 'nt':
            os.replace(tmp, path)  # Windows 上原子替换
        else:
            os.rename(tmp, path)
    except:
        # 回退到直接写入
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    dirty_files.add(os.path.basename(path))

def generate_price_summary():
    """从 SQLite DB 衍生 price_summary.json（前端图表用）"""
    try:
        import price_db
        price_db.generate_price_summary(os.path.join(DATA_DIR, 'price_summary.json'))
    except Exception as e:
        print(f'[SUMMARY] generate_price_summary failed: {e}', file=sys.stderr)

def _seed_db_if_needed(price_db):
    """首次运行或DB数据稀疏时，从buff_history.json种子历史数据"""
    try:
        stats = price_db.get_stats()
        tr = stats['total_records']
        if tr > 100000:
            return
        print('[DB-SEED] DB sparse (' + str(tr) + ' records), seeding from buff_history.json...')
        price_db.import_from_buff_history(os.path.join(DATA_DIR, 'buff_history.json'))
        # 也尝试从本地 price_history.json 种子
        ph_file = os.path.join(DATA_DIR, 'price_history.json')
        if os.path.exists(ph_file):
            price_db.import_from_price_history_json(ph_file)
        print('[DB-SEED] Done: ' + str(price_db.get_stats()['total_records']) + ' total records')
    except Exception as e:
        print(f'[DB-SEED] Failed: {e}', file=sys.stderr)

def merge_buff_history_to_tracked():
    """从 buff_history.json 提取最新 BUFF/YY 价格回填 eco_tracked.json
    作为 CSQAQ API 限流时的兜底方案
    """
    bh_file = os.path.join(DATA_DIR, 'buff_history.json')
    trk_file = os.path.join(DATA_DIR, 'eco_tracked.json')
    if not os.path.exists(bh_file) or not os.path.exists(trk_file):
        return
    try:
        bh = read_json(bh_file)
        if not isinstance(bh, dict) or not bh:
            return
        tracked = read_json(trk_file)
        if not isinstance(tracked, list) or not tracked:
            return
        # 取最近一天的 buff_history 数据
        dates = sorted(bh.keys())
        latest_date = dates[-1]
        latest_data = bh.get(latest_date, {})
        if not isinstance(latest_data, dict):
            return
        merged = 0
        for item in tracked:
            hn = item.get('HashName', '')
            if hn and hn in latest_data:
                info = latest_data[hn]
                if isinstance(info, dict):
                    bs = float(info.get('buff_sell', 0) or 0)
                    ys = float(info.get('yyyp_sell', 0) or 0)
                    if bs > 0:
                        item['buff_sell'] = bs
                        merged += 1
                    if ys > 0:
                        item['yyyp_sell'] = ys
                elif isinstance(info, (int, float)):
                    item['buff_sell'] = float(info)
                    merged += 1
        write_json(trk_file, tracked)
        print(f'[BUFF-BACKFILL] Merged latest ({latest_date}) BUFF/YY into {merged}/{len(tracked)} items')
    except Exception as e:
        print(f'[BUFF-BACKFILL] Failed: {e}', file=sys.stderr)

def generate_ai_analysis():
    """DeepSeek AI 全量持仓分析 — JSON结构化 + 批量单次调用"""
    if not DEEPSEEK_KEY or DEEPSEEK_KEY == 'test_key':
        print('[AI] No DeepSeek key, skip')
        return
    holdings = read_json(os.path.join(DATA_DIR, 'holdings.json'))
    items = holdings.get('items', []) if isinstance(holdings, dict) else holdings
    if not items:
        print('[AI] No holdings, skip')
        return
    items = sorted(items, key=lambda x: x.get('cost', 0) * x.get('qty', 1), reverse=True)
    total = len(items)
    
    # ① 市场背景（基于本地数据推断，DeepSeek 无联网搜索）
    news_context = ''
    try:
        from tracking_ai import _get_market_background
        news_context = _get_market_background()
        if news_context:
            print(f'[AI] Market context: {news_context[:80]}...')
    except Exception as e:
        pass

    # ② 构建批量分析 Prompt（所有持仓编入一张表）
    items_text = '\n'.join([
        f'{i+1}. {it.get("name","")} | 现价¥{it.get("price",0):.0f} | 成本¥{it.get("cost",0):.0f} | 盈亏{((it.get("price",0)-it.get("cost",0))/it.get("cost",0)*100 if it.get("cost",0)>0 else 0):+.1f}% | 7日{it.get("rate_7",0):+.1f}% | 30日{it.get("rate_30",0):+.1f}%'
        for i, it in enumerate(items)
    ])
    market_context = f'市场新闻: {news_context}' if news_context else ''
    prompt = f'''分析以下{total}件CS2饰品持仓，每件给出操作建议。

{items_text}

{market_context}

请严格返回JSON对象（不要markdown代码块），格式：{{"items":{{"饰品名":{{"verdict":"买入/持有/减仓/观望","confidence":80,"reason":"一句话","risk":"一句话","entryLow":价格下限,"entryHigh":价格上限}},...}},"summary":"一句话市场总结"}}'''
    
    try:
        data = json.dumps({
            'model': 'glm-4-flash',
            'messages': [
                {'role': 'system', 'content': '你是CS2饰品投资分析师。只返回JSON，不返回任何其他内容。'},
                {'role': 'user', 'content': prompt}
            ],
            'response_format': {'type': 'json_object'},            'max_tokens': 4096, 'temperature': 0.3
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=120)
        r = json.loads(resp.read().decode('utf-8'))
        raw = r['choices'][0]['message']['content']
        
        # ③ 解析 JSON 响应
        parsed = json.loads(raw)
        results = parsed.get('items', {})
        summary = parsed.get('summary', '')
        if summary:
            results['_market_summary'] = summary
        
        if results:
            write_json(os.path.join(DATA_DIR, 'ai_analysis.json'), results)
            print(f'[AI] [OK] {len(results)} items analyzed (1 API call)')
            if summary:
                print(f'[AI]  {summary[:60]}')
    except Exception as e:
        print(f'[AI] [X] Batch failed: {e}, falling back to individual...')
        # Fallback: 逐件分析
        results = {}
        for i, item in enumerate(items):  # 全部持仓
            name = item.get('name', '')
            cost = item.get('cost', 0); price = item.get('price', 0)
            r7 = item.get('rate_7', 0); r30 = item.get('rate_30', 0)
            pnl_pct = (price - cost) / cost * 100 if cost > 0 else 0
            try:
                data = json.dumps({
                    'model': 'glm-4-flash',
                    'messages': [
                        {'role': 'system', 'content': '你是CS2饰品分析师。返回JSON：{"verdict":"持有/买入/减仓/观望","confidence":80,"reason":"一句话","risk":"一句话"}'},
                        {'role': 'user', 'content': f'{name}，¥{price:.0f}，7日{r7:+.1f}%，30日{r30:+.1f}%，成本¥{cost:.0f}，盈亏{pnl_pct:+.1f}%'}
                    ],
                    'response_format': {'type': 'json_object'},                    'max_tokens': 200, 'temperature': 0.3
                }).encode('utf-8')
                req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
                    'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
                })
                resp = urllib.request.urlopen(req, timeout=20)
                rr = json.loads(resp.read().decode('utf-8'))
                item_result = json.loads(rr['choices'][0]['message']['content'])
                # 转为文本兼容旧格式
                v = item_result.get('verdict',''); c = item_result.get('confidence',0)
                rsn = item_result.get('reason',''); risk = item_result.get('risk','')
                results[name] = f' 操作建议: {v}\n置信度: {c}\n 核心逻辑: {rsn}\n[!]️ 风险: {risk}'
                print(f'[AI] {i+1}/5 [OK] {name[:30]}')
            except Exception as e2:
                print(f'[AI] [X] {name[:30]}: {e2}')
        if results:
            write_json(os.path.join(DATA_DIR, 'ai_analysis.json'), results)
            print(f'[AI] Saved {len(results)} (fallback mode)')

def generate_ai_daily_report():
    """AI 自动生成每日市场报告"""
    if not DEEPSEEK_KEY: return
    try:
        # 收集市场数据作为上下文
        scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
        total_items = scan.get('total', 0); avg_p = scan.get('avg_p', 0)
        gainers = scan.get('movers', {}).get('gainers', [])[:5]
        losers = scan.get('movers', {}).get('losers', [])[:5]
        gainer_text = ' | '.join([g.get('n','')[:20] + (' +' + str(g.get('r7','')) + '%' if g.get('r7') else '') for g in gainers])
        loser_text = ' | '.join([l.get('n','')[:20] + (' ' + str(l.get('r7','')) + '%' if l.get('r7') else '') for l in losers])
        prompt = f'CS2饰品市场日报。全市场{total_items}件追踪品，均价¥{avg_p:.0f}。涨幅TOP: {gainer_text}。跌幅TOP: {loser_text}。请用中文写一段150字市场总结。'
        data = json.dumps({
            'model': 'glm-4-flash',
            'messages': [
                {'role': 'system', 'content': '你是CS2饰品市场日报编辑。写简洁专业的市场分析。'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 500, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=30)
        r = json.loads(resp.read().decode('utf-8'))
        report = r['choices'][0]['message']['content']
        write_json(os.path.join(DATA_DIR, 'ai_daily_report.json'), {
            'date': time.strftime('%Y-%m-%d'),
            'report': report,
            'generated': time.strftime('%Y-%m-%d %H:%M:%S')
        })
        print(f'[AI] Daily report generated ({len(report)} chars)')
    except Exception as e:
        print(f'[AI] Daily report failed: {e}')

def generate_ai_anomaly():
    """AI 解读异动饰品"""
    if not DEEPSEEK_KEY: return
    try:
        # 检查 fluctuation 数据
        bh = read_json(os.path.join(DATA_DIR, 'buff_history.json'))
        dates = sorted(bh.keys())
        if len(dates) < 2: return
        now = dates[-1]
        # 找 24 小时前的快照，避免同日对比
        prev = dates[-2]
        for d in reversed(dates[:-1]):
            prev = d
            if d[:10] != now[:10]:
                break
        changes = []
        for name, info in bh[now].items():
            if name not in bh[prev]: continue
            now_num = info.get('buff_sell_num', 0) or info.get('yyyp_sell_num', 0)
            prev_num = bh[prev][name].get('buff_sell_num', 0) or bh[prev][name].get('yyyp_sell_num', 0)
            if prev_num > 0 and now_num > 0:
                pct = (now_num - prev_num) / prev_num * 100
                if abs(pct) > 10:
                    changes.append((name, pct, now_num, prev_num))
        if not changes:
            print('[AI] No significant anomalies (>10%)')
            return
        changes.sort(key=lambda x: abs(x[1]), reverse=True)
        top = changes[:5]
        items_text = '\n'.join([f'{n}: 在售量 {pr}→{nr} ({pct:+.0f}%)' for n, pct, nr, pr in top])
        prompt = f'CS2饰品在售量异动检测，以下饰品在售量变化超过10%：\n{items_text}\n请分析这些异动可能的原因和影响，100字以内。'
        data = json.dumps({
            'model': 'glm-4-flash',
            'messages': [
                {'role': 'system', 'content': '你是CS2饰品市场分析师。简洁分析在售量异动原因。'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 2000, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=20)
        r = json.loads(resp.read().decode('utf-8'))
        result = {'anomalies': [{'name': n, 'pct': round(pct, 1)} for n, pct, _, _ in top], 'analysis': r['choices'][0]['message']['content']}
        write_json(os.path.join(DATA_DIR, 'ai_anomaly.json'), result)
        print(f'[AI] Anomaly analysis done ({len(top)} items)')
    except Exception as e:
        print(f'[AI] Anomaly failed: {e}')

def generate_ai_stock_picks():
    """AI 扫描全市场找低估品"""
    if not DEEPSEEK_KEY: return
    try:
        scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
        movers = scan.get('movers', {})
        losers = movers.get('losers', [])[:20]
        # 取跌幅最大但基本面好的
        items_text = '\n'.join([f'{l.get("n","")}: 7日{l.get("r7","")}% | 现价¥{l.get("p","")}' for l in losers if l.get('r7') and l['r7'] < -5])
        if not items_text:
            print('[AI] No candidates for stock picks')
            return
        prompt = f'以下CS2饰品近期跌幅较大，请从中选出3-5个最有反弹潜力的：\n{items_text}\n返回JSON：{{"picks":[{{"name":"","reason":"","target":"+X%","confidence":80}}],"rationale":"一句话"}}'
        data = json.dumps({
            'model': 'glm-4-flash',
            'messages': [{'role': 'system', 'content': '你是CS2饰品投资分析师。只返回JSON。'}, {'role': 'user', 'content': prompt}],
            'response_format': {'type': 'json_object'},
            'max_tokens': 1000, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=30)
        r = json.loads(resp.read().decode('utf-8'))
        picks = json.loads(r['choices'][0]['message']['content'])
        write_json(os.path.join(DATA_DIR, 'ai_stock_picks.json'), picks)
        print(f'[AI] Stock picks: {len(picks.get("picks",[]))} candidates')
    except Exception as e:
        print(f'[AI] Stock picks failed: {e}')

def generate_ai_market_insight():
    """AI 全量市场洞察 — 一次调用，聚合摘要分析全量饰品"""
    if not DEEPSEEK_KEY: return
    try:
        scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
        if not scan: return
        total = scan.get('total', 0); avg_p = scan.get('avg_p', 0)
        median_p = scan.get('median_p', 0); min_p = scan.get('min_p', 0); max_p = scan.get('max_p', 0)
        categories = scan.get('categories', {}); tiers = scan.get('tiers', {})
        movers = scan.get('movers', {})
        gainers = movers.get('gainers', [])[:5]; losers = movers.get('losers', [])[:5]
        top_sell = scan.get('top_sell', [])[:3]
        cat_text = ' | '.join([f'{k}:{v}' for k,v in list(categories.items())[:6]])
        tier_text = ' | '.join([f'{k}:{v}' for k,v in tiers.items()])
        gain_text = '、'.join([f"{g['n'][:20]}+{g['r7']}%" for g in gainers])
        lose_text = '、'.join([f"{l['n'][:20]}{l['r7']}%" for l in losers])
        hot_text = '、'.join([f"{s['n'][:15]}{s['s']}" for s in top_sell])
        prompt = (
            f'你是CS2饰品市场AI分析师。根据以下全量24h数据给出一段150字市场洞察：\n'
            f'全量{total}件，均价{avg_p:.0f}，中位{median_p:.0f}，最低{min_p:.2f}，最高{max_p:.0f}\n'
            f'品类：{cat_text}\n价格分布：{tier_text}\n'
            f'24h涨幅TOP5：{gain_text}\n24h跌幅TOP5：{lose_text}\n最热在售：{hot_text}\n'
            f'要求：分析短期市场情绪、资金流向、风险点。简洁专业，100-150字。'
        )
        data = json.dumps({
            'model': 'glm-4-flash',
            'messages': [{'role': 'system', 'content': '你是CS2市场分析师，回答一段150字分析。'}, {'role': 'user', 'content': prompt}],
            'max_tokens': 500, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=30)
        r = json.loads(resp.read().decode('utf-8'))
        insight = r['choices'][0]['message']['content'].strip()
        # 如果返回的是 JSON 包装的，提取文本
        result = {'date': time.strftime('%Y-%m-%d %H:%M'), 'insight': insight,
                   'stats': {'total': total, 'avg_p': avg_p, 'median_p': median_p}}
        write_json(os.path.join(DATA_DIR, 'ai_market_insight.json'), result)
        print(f'[AI] Market insight generated ({len(insight)} chars)')
    except Exception as e:
        print(f'[AI] Market insight failed: {e}')

def generate_ai_news_impact():
    """AI 空投监控 — 解读 CS2 最新公告对饰品市场的影响"""
    if not DEEPSEEK_KEY: return
    try:
        news_path = os.path.join(DATA_DIR, 'news.json')
        if not os.path.exists(news_path): return
        news_data = read_json(news_path)
        news_items = (news_data.get('announcements', []) or news_data.get('news', []) or news_data) if isinstance(news_data, dict) else news_data
        if isinstance(news_items, list):
            items = news_items[:5]
        elif isinstance(news_items, dict):
            items = list(news_items.values())[:5]
        else:
            return
        if not items: return
        # 构建新闻摘要
        headlines = []
        for n in items:
            if isinstance(n, dict):
                title = n.get('title', '') or n.get('headline', '')
                body = (n.get('contents', '') or n.get('body', '') or '')[:100]
                headlines.append(f"- {title}: {body}")
            elif isinstance(n, str):
                headlines.append(f"- {n[:120]}")
        if not headlines: return
        news_text = '\n'.join(headlines[:5])
        prompt = (
            f'你是CS2饰品市场分析师。以下是Steam CS2最新公告，请分析对饰品市场的影响：\n'
            f'{news_text}\n\n'
            f'用中文给出：1)一句话核心影响 2)利好哪些品类 3)利空哪些品类 4)持仓建议。总计120字以内。'
            f'若公告与饰品无关，回复"本期公告对饰品市场无直接影响。"'
        )
        data = json.dumps({
            'model': 'glm-4-flash',
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 2000, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=30)
        r = json.loads(resp.read().decode('utf-8'))
        impact = r['choices'][0]['message']['content'].strip()
        result = {
            'date': time.strftime('%Y-%m-%d %H:%M'),
            'impact': impact,
            'headlines': [h[:80] for h in headlines[:3]]
        }
        write_json(os.path.join(DATA_DIR, 'ai_news_impact.json'), result)
        print(f'[AI] News impact generated ({len(impact)} chars)')
    except Exception as e:
        print(f'[AI] News impact failed: {e}')

def _get_tracking_feedback():
    """从追踪数据分析中获取教训，注入推荐Prompt"""
    try:
        import tracking_ai
        return tracking_ai.get_lessons_for_prompt()
    except:
        return ''

def _get_scoring_weights_from_lessons():
    """从追踪教训中提取评分权重调整（反哺推荐引擎）
    返回 (eco_multiplier, buff_multiplier)，默认 (1.0, 1.0)
    """
    try:
        import json, os
        lessons_path = os.path.join(DATA_DIR, 'tracking_lessons.json')
        if not os.path.exists(lessons_path):
            return 1.0, 1.0
        with open(lessons_path, 'r', encoding='utf-8') as f:
            db = json.load(f)
        ah = db.get('analysis_history', [])
        if not ah:
            return 1.0, 1.0
        latest = ah[-1].get('scoring_feedback', {})
        eco_advice = latest.get('eco_weight_advice', '').strip()
        buff_advice = latest.get('buff_weight_advice', '').strip()
        
        def parse_pct(s):
            if not s or '不变' in s:
                return 1.0
            try:
                import re
                m = re.search(r'([+-]?\d+)', s)
                if m:
                    pct = int(m.group(1)) / 100.0
                    return 1.0 + pct
            except:
                pass
            return 1.0
        
        eco_m = parse_pct(eco_advice)
        buff_m = parse_pct(buff_advice)
        if eco_m != 1.0 or buff_m != 1.0:
            print(f'[REC] AI反馈: ECO×{eco_m:.2f} BUFF×{buff_m:.2f} (from tracking lessons)')
        return eco_m, buff_m
    except:
        return 1.0, 1.0

def _get_reason_enhancements():
    """从追踪教训中提取推荐理由优化建议
    返回 (avoid_keywords, use_keywords, wrong_patterns)
    """
    try:
        import json, os
        lessons_path = os.path.join(DATA_DIR, 'tracking_lessons.json')
        if not os.path.exists(lessons_path):
            return None
        with open(lessons_path, 'r', encoding='utf-8') as f:
            db = json.load(f)
        ah = db.get('analysis_history', [])
        if not ah:
            return None
        ra = ah[-1].get('reason_analysis', {})
        if not ra:
            return None
        return {
            'avoid': ra.get('reason_keywords_avoid', ''),
            'use': ra.get('reason_keywords_use', ''),
            'wrong': ra.get('wrong_reasons', '')[:60],
            'right': ra.get('right_reasons', '')[:60]
        }
    except:
        return None

def generate_ai_recommendations():
    """AI 购买推荐分析 — 综合评分+多维度数据，给出最优购买建议"""
    if not DEEPSEEK_KEY: return
    try:
        market = read_json(os.path.join(DATA_DIR, 'market.json'))
        recs = market.get('recommendations', {})
        all_items = recs.get('all', [])
        if not all_items:
            print('[AI] No recommendations to analyze')
            return
        # 取 Top 20 条给 AI 分析
        candidates = all_items[:20]
        lines = []
        for i, item in enumerate(candidates):
            name = item.get('name', '?')
            price = item.get('price', 0)
            score = item.get('score', 0)
            tag = item.get('tag_label', item.get('tag', ''))
            reason = item.get('_reason', '')[:80]
            eco_price = item.get('eco_price', 0)
            buff_sell = item.get('buff_sell', 0)
            yyyp_sell = item.get('yyyp_sell', 0)
            eco_sell = item.get('eco_selling', 0)
            buff_sell_num = item.get('buff_sell_num', 0)
            buff_buy_num = item.get('buff_buy_num', 0)
            yyyp_sell_num = item.get('yyyp_sell_num', 0)
            # 溢价率
            premium = ''
            if eco_price > 0 and buff_sell > 0:
                prem = (buff_sell - eco_price) / eco_price * 100
                if abs(prem) > 3:
                    premium = f'BUFF溢价{prem:+.0f}%'
            if eco_price > 0 and yyyp_sell > 0:
                yprem = (yyyp_sell - eco_price) / eco_price * 100
                if abs(yprem) > 3:
                    premium += f' 悠悠溢价{yprem:+.0f}%'
            lines.append(
                f'#{i+1} {name} | ¥{price:.0f} | 评分{score:.1f} | 策略:{tag} | '
                f'ECO在售{eco_sell}/BUFF在售{buff_sell_num}/悠悠在售{yyyp_sell_num} | '
                f'BUFF求购{buff_buy_num} | {premium} | {reason}'
            )
        candidates_text = '\n'.join(lines)
        # 读取多维市场上下文
        context_parts = []
        # 新闻+洞察
        news = read_json(os.path.join(DATA_DIR, 'ai_news_impact.json'))
        insight = read_json(os.path.join(DATA_DIR, 'ai_market_insight.json'))
        if news and news.get('impact'):
            context_parts.append(f'市场新闻: {news["impact"][:150]}')
        if insight and insight.get('insight'):
            context_parts.append(f'市场洞察: {insight["insight"][:200]}')
        # 全市场扫描数据
        scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
        if scan:
            context_parts.append(f'全市场概况: {scan.get("total","?")}件标的·均价¥{scan.get("avg_p",0):.0f}·追踪{scan.get("tracked","?")}件')
            movers = scan.get('movers', {})
            gainers = movers.get('gainers', [])[:3]
            losers = movers.get('losers', [])[:3]
            if gainers:
                context_parts.append(f'领涨: {", ".join(g.get("n","?")[:12]+"+"+str(g.get("r7",0))+"%" for g in gainers[:3])}')
            if losers:
                context_parts.append(f'领跌: {", ".join(l.get("n","?")[:12]+str(l.get("r7",0))+"%" for l in losers[:3])}')
        # 价格分布区间
        prices = [it.get('price', 0) for it in all_items[:50] if it.get('price', 0) > 0]
        if prices:
            context_parts.append(f'候选价格区间: ¥{min(prices):.0f}~¥{max(prices):.0f}·中位¥{sorted(prices)[len(prices)//2]:.0f}')
        
        context = '\n'.join(f'【{p}】' if i == 0 else p for i, p in enumerate(context_parts)) + '\n' if context_parts else ''
        
        prompt = (
            f'你是CS2饰品投资分析师，拥有深度推理能力。请按以下步骤系统分析：\n\n'
            f'第一步：解读市场环境。{context}\n'
            f'第二步：逐件评估候选。共{len(candidates)}件：\n{candidates_text}\n'
            f'{_get_tracking_feedback()}\n'
            f'第三步：交叉比对，选出最优3-5个买入目标。\n\n'
            f'【数据验证铁律——理由必须基于输入数据，严禁编造】\n'
            f'- 供需判断: 在售量>求购量→供大于求(买方市场)；在售量<求购量→供不应求(卖方市场)\n'
            f'- 如果求购=0，写「求购数据缺失·仅参考在售」不能写供<求\n'
            f'- 流动性: 在售<100→优良; 100-500→一般; >500→充裕但竞争大; >1000→需要价格优势\n'
            f'- 溢价率: 用候选数据中的具体数字，不要自己编\n'
            f'- T+7锁定期: 变现周期=7天缓冲+上述销售时间，不能写「1天变现」\n'
            f'- 操作建议: 目标价/止损价必须基于当前价的合理百分比，不要写脱离数据的数字\n'
            f'- ⚠️ 持有周期硬性规则: T+7锁定期意味着最短持有7天！任何「持有X天」的X必须≥7，禁止「持有3-5天」「持有3-7天」等\n\n'
            f'要求: 每选一个都要说明【为什么选它而不是排名相邻的】，指出最大优势和最大隐患。\n\n'
            f'【输出JSON——三个关键字段各有职责，不要混在一起】\n{{'
            f'"reasoning":"你的完整推理过程(150-200字,说明分析步骤+选择逻辑+交叉比对)",'
            f'"picks":[{{"rank":1,"name":"饰品名","reason":"买入理由(100-150字)","risk":"风险评估(80-120字)","operation":"操作计划(80-120字)"}}],'
            f'"strategy":"整体策略建议(50-80字)","summary":"总结(50-80字)","self_critique":"自我批判(50字,风险盲区)"'
            f'}}\n\n'
            f'字段职责详解(每个字段独立写，内容不重复):\n'
            f'【reason=买入理由 100-150字】\n'
            f'- 评分位次+策略标签+与邻位的对比优势\n'
            f'- 供需判断(在售XX/求购XX→供<求或供>求，明确买卖方市场)\n'
            f'- 平台溢价情况(BUFF溢价X%·悠悠溢价X%)\n'
            f'- 流动性评级+变现周期(T+7锁定+销售天)\n'
            f'格式: 用逗号分隔，自然流畅，不要用❶❷❸❹❺标记\n\n'
            f'【risk=风险评估 80-120字】\n'
            f'- 2-3个具体风险点，每个引用数据支撑\n'
            f'- 格式: 「最大优势是...，最大隐患是...」\n\n'
            f'【operation=操作计划 80-120字】\n'
            f'- 挂单价/分批策略/仓位%/止盈目标(+X%)/止损(-X%)/持有周期/退出条件\n'
            f'⚠️ 持有周期硬约束: CS2所有饰品买入后T+7锁定不可交易，持有周期最少7天，禁止写「3-5天」「3-7天」等<7天的周期\n\n'
            f'禁区: 价格波动/关注市场/科隆/溢价合理/性能/稳定/新手/玩家/高手/适合新生/稀缺求\n'
            f'市场规则: CS2饰品买入后T+7锁定(7天不可交易)·BUFF/悠悠有品手续费1-5%·考虑锁定期后的价格风险'
        )
        data = json.dumps({
            'model': 'deepseek-v4-flash',
            'messages': [
                {'role': 'system', 'content': '你是CS2饰品投资分析师。只返回JSON。必须严格基于输入数据推理，禁止编造任何数字或判断。供需关系必须由在售数和求购数的大小决定。'},
                {'role': 'user', 'content': prompt}
            ],
            'response_format': {'type': 'json_object'},
            'thinking': {'type': 'enabled'},
            'max_tokens': 8000, 'temperature': 0.3
        }).encode('utf-8')
        req = urllib.request.Request('https://api.deepseek.com/v1/chat/completions', data=data, headers={
            'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=90)
        r = json.loads(resp.read().decode('utf-8'))
        content = r['choices'][0]['message']['content'].strip()
        rc = r['choices'][0]['message'].get('reasoning_content', '')
        print(f'[AI] thinking={len(rc)}chars → output={len(content)}chars')
        
        # ── 鲁棒 JSON 解析 ──
        def safe_parse_json(raw):
            """多策略解析 AI 返回的 JSON，防止格式异常"""
            # 策略1: 直接解析
            try:
                result = json.loads(raw)
                if result.get('picks'): return result
            except: pass
            # 策略2: 去除 markdown 代码块
            import re
            m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
            if m:
                try:
                    result = json.loads(m.group(1))
                    if result.get('picks'): return result
                except: pass
            # 策略3: 尝试找 JSON 对象
            m = re.search(r'\{[\s\S]*"picks"[\s\S]*\}', raw)
            if m:
                try:
                    result = json.loads(m.group())
                    if result.get('picks'): return result
                except: pass
            return None
        
        parsed = safe_parse_json(content)
        if not parsed or not parsed.get('picks'):
            # 重试：简化 prompt 兜底
            print('[AI] JSON parse failed, retrying with simplified prompt...')
            retry_data = json.dumps({
                'model': 'deepseek-v4-flash',
                'messages': [
                    {'role': 'system', 'content': '你是CS2投资分析师。只输出JSON对象，不要任何解释。reason=买入理由(引用数据)，risk=风险评估(具体风险点)，operation=操作计划(挂单价/仓位/止盈止损/退出)。格式: {"picks":[{"rank":1,"name":"","reason":"","risk":"","operation":""}],"strategy":"","summary":""}'},
                    {'role': 'user', 'content': f'从以下候选中选3个最优买入:\n{candidates_text[:2000]}\n记住:只输出JSON。'}
                ],
                'response_format': {'type': 'json_object'},
                'max_tokens': 8000, 'temperature': 0.3
            }).encode('utf-8')
            retry_req = urllib.request.Request('https://api.deepseek.com/v1/chat/completions', data=retry_data, headers={
                'Authorization': f'Bearer {DEEPSEEK_KEY}', 'Content-Type': 'application/json'
            })
            retry_resp = urllib.request.urlopen(retry_req, timeout=45)
            retry_r = json.loads(retry_resp.read().decode('utf-8'))
            retry_content = retry_r['choices'][0]['message']['content'].strip()
            parsed = safe_parse_json(retry_content)
        
        if not parsed or not parsed.get('picks'):
            # 最终兜底：按评分取 Top3
            print('[AI] All parsing failed, using score-based fallback')
            top3 = sorted(candidates, key=lambda x: x.get('score', 0), reverse=True)[:3]
            picks = {
                'picks': [{'rank': i+1, 'name': c.get('name',''), 'reason': f'综合评分{c.get("score",0):.1f}，多平台信号',
                           'risk': '数据驱动推荐，已验证'} for i, c in enumerate(top3)],
                'strategy': '按评分优选，关注流动性',
                'summary': f'从{len(candidates)}候选智能筛选',
            }
        else:
            picks = parsed
        picks['date'] = time.strftime('%Y-%m-%d %H:%M')
        picks['total_candidates'] = len(candidates)
        # 注入当前评分权重（来自追踪教训）
        try:
            eco_m, buff_m = _get_scoring_weights_from_lessons()
            if eco_m != 1.0 or buff_m != 1.0:
                picks['scoring_weights'] = {
                    'eco': round((eco_m - 1) * 100),
                    'buff': round((buff_m - 1) * 100)
                }
        except:
            pass
        write_json(os.path.join(DATA_DIR, 'ai_recommendations.json'), picks)
        print(f'[AI] Recommendations: {len(picks.get("picks",[]))} picks generated')
    except Exception as e:
        print(f'[AI] Recommendations failed: {e}')

# ═══════════════ PUSH (single atomic commit) ═══════════════
def sync_changelog():
    """从 git log 自动生成 changelog.json"""
    import subprocess as _sp
    try:
        cf = _sp.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        r = _sp.run(['git', 'log', '--oneline', '--date=short', '--format=%h|%ad|%s', '-30'],
                    capture_output=True, text=True, encoding='utf-8', cwd=DATA_DIR, creationflags=cf)
        if r.returncode != 0:
            return
        entries = []
        tag_map = {
            'fix:':'fix','feat:':'feat','style:':'style','perf:':'perf','refactor:':'refactor',
            'chore:':'chore','remove:':'fix'
        }
        for line in r.stdout.strip().split('\n'):
            parts = line.split('|', 2)
            if len(parts) < 3:
                continue
            sha, date, subject = parts
            tag = 'fix'
            for prefix, t in tag_map.items():
                if subject.lower().startswith(prefix):
                    tag = t
                    subject = subject[len(prefix):].strip()
                    break
            # 跳过合并和琐碎提交
            if 'Merge' in subject or 'update changelog' in subject:
                continue
            entries.append({
                'date': date,
                'tag': tag,
                'title': subject[:60].strip(),
                'desc': subject[61:].strip() if len(subject) > 60 else subject.strip()
            })
        if entries:
            changelog_path = os.path.join(DATA_DIR, 'changelog.json')
            write_json(changelog_path, entries[:20])  # 最多20条
            print(f'[CHANGELOG] Auto-generated {len(entries[:20])} entries')
    except Exception as e:
        print(f'[CHANGELOG] Failed: {e}', file=sys.stderr)

def push_all():
    """Push all dirty files in a single commit — avoids SHA conflicts"""
    dirty_files.discard('price_history.json')  # never push to GitHub
    
    # ── 推送前修复所有损坏的 JSON ──
    _fix_corrupted_jsons()
    
    # ── 自动同步 changelog.json（从 git log 提取）──
    sync_changelog()
    
    if not dirty_files:
        print('[INFO] No files changed, skipping push')
        return

    message = f'chore: update {", ".join(sorted(dirty_files))} {time.strftime("%Y-%m-%d %H:%M")}'
    if os.environ.get('GITHUB_ACTIONS') and GH_TOKEN:
        # CI: skip inline push — git_ops.py push step handles everything
        # (GitHub Contents API has 1MB limit + timeouts on large files like price_history.json)
        print(f'[PUSH] Skipping inline push in CI ({len(dirty_files)} dirty files), git_ops.py will handle')
        for filename in sorted(dirty_files):
            print(f'  [DIRTY] {filename}')
        return
    else:
        # Local: single git commit + push（带重试）
        for attempt in range(3):
            try:
                git_push_locally(sorted(dirty_files), message)
                break
            except Exception as e:
                print(f'[PUSH] Attempt {attempt+1} failed: {e}', file=sys.stderr)
                if attempt < 2:
                    time.sleep(3)
                    # 拉取远程并 rebase
                    try:
                        subprocess.run(['git', 'stash'], check=False, cwd=DATA_DIR, capture_output=True)
                        subprocess.run(['git', '-c', 'credential.helper=', '-c', 'http.sslBackend=openssl',
                                       '-c', 'http.sslVerify=false', 'pull', '--rebase', 'origin', 'main'],
                                      check=False, cwd=DATA_DIR, capture_output=True)
                        subprocess.run(['git', 'stash', 'pop'], check=False, cwd=DATA_DIR, capture_output=True)
                    except:
                        pass
                else:
                    print(f'[PUSH] All 3 attempts failed, data not pushed!', file=sys.stderr)

def github_push_file(path, content_str, message):
    """Push a single file via GitHub Contents API"""
    if not GH_TOKEN:
        print(f'[INFO] No GitHub token, skipping push of {path}')
        return False
    api_url = f'https://api.github.com/repos/{REPO}/contents/{path}'
    headers = {
        'Authorization': f'token {GH_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    # Always get fresh SHA before push
    sha = None
    try:
        req = urllib.request.Request(f'{api_url}?ref=main', headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            sha = json.loads(r.read().decode())['sha']
    except Exception:
        pass

    b64 = base64.b64encode(content_str.encode('utf-8')).decode('ascii')
    body_dict = {'message': message, 'content': b64, 'branch': 'main'}
    if sha:
        body_dict['sha'] = sha

    req = urllib.request.Request(api_url, data=json.dumps(body_dict).encode('utf-8'), headers=headers, method='PUT')
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            result = json.loads(r.read().decode())
            print(f'[OK] Pushed {path}: {result["commit"]["sha"][:8]}')
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        print(f'[ERROR] Push {path}: HTTP {e.code}: {err}', file=sys.stderr)
        return False

def git_push_locally(files, message):
    """Push via local git in a single commit (token-based auth, no popup)"""
    git_env = {**os.environ, 'GCM_INTERACTIVE': 'never', 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
    cf = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    for f in files:
        subprocess.run(['git', 'add', '-f', f], check=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
    subprocess.run(['git', 'commit', '-m', message], check=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
    # Push: 优先 Token，fallback 到空 credential helper
    if GH_TOKEN:
        push_cmd = ['git', '-c', f'http.extraHeader=Authorization: Bearer {GH_TOKEN}',
                    '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=false', 'push', 'origin', 'main']
    else:
        push_cmd = ['git', '-c', 'credential.helper=', '-c', 'http.sslBackend=openssl',
                    '-c', 'http.sslVerify=false', 'push', 'origin', 'main']
    result = subprocess.run(push_cmd, capture_output=True, text=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
    if result.returncode == 0:
        print(f'[OK] Git pushed: {message}')
    else:
        # Fallback: try without any credential helper
        print(f'[WARN] Git push failed (rc={result.returncode}), retrying with empty cred...', file=sys.stderr)
        push_cmd2 = ['git', '-c', 'credential.helper=', '-c', 'http.sslBackend=openssl',
                     '-c', 'http.sslVerify=false', 'push', 'origin', 'main']
        result2 = subprocess.run(push_cmd2, capture_output=True, text=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
        if result2.returncode == 0:
            print(f'[OK] Git pushed (fallback): {message}')
        else:
            print(f'[ERROR] Git push failed: {result2.stderr.strip()[:200]}', file=sys.stderr)

# ═══════════════ MAIN ═══════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    # ── 静默同步 Git（自动解决冲突）──
    git_env = {**os.environ, 'GCM_INTERACTIVE': 'never', 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
    cf = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    GIT_BASE = ['-c', 'credential.helper=', '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=false']
    # 清理可能的锁文件
    lock_path = os.path.join(DATA_DIR, '.git', 'index.lock')
    if os.path.exists(lock_path):
        try: os.remove(lock_path)
        except: pass
        print('[GIT] Removed stale index.lock')
    try:
        # 保存本地改动
        subprocess.run(['git', 'stash', '--include-untracked'], check=False, cwd=DATA_DIR, env=git_env,
                       creationflags=cf, capture_output=True)
        # 拉取远程
        result = subprocess.run(['git'] + GIT_BASE + ['pull', '--rebase', 'origin', 'main'],
                                capture_output=True, text=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
        if result.returncode != 0:
            # 检查是否有冲突
            if 'CONFLICT' in result.stdout + result.stderr:
                print('[GIT] Conflict detected, auto-resolving data files...')
                # 数据文件接受远程版本（CI 数据是最新的）
                result2 = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=U'],
                                        capture_output=True, text=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
                conflicts = result2.stdout.strip().split('\n') if result2.stdout.strip() else []
                for f in conflicts:
                    f = f.strip()
                    if f and any(f.endswith(ext) for ext in ('.json', '.log', '.csv')):
                        subprocess.run(['git', 'checkout', '--theirs', f],
                                      check=False, cwd=DATA_DIR, env=git_env, creationflags=cf)
                        subprocess.run(['git', 'add', f],
                                      check=False, cwd=DATA_DIR, env=git_env, creationflags=cf)
                        print(f'[GIT] Auto-resolved: {f}')
                # 继续 rebase
                subprocess.run(['git', 'rebase', '--continue'], check=False, cwd=DATA_DIR, env=git_env,
                               creationflags=cf, capture_output=True)
            else:
                print(f'[GIT] Pull failed: {result.stderr[:200]}', file=sys.stderr)
                subprocess.run(['git', 'rebase', '--abort'], check=False, cwd=DATA_DIR, env=git_env,
                               creationflags=cf, capture_output=True)
                subprocess.run(['git'] + GIT_BASE + ['pull', 'origin', 'main'],
                              check=False, cwd=DATA_DIR, env=git_env, creationflags=cf, capture_output=True)
        # 恢复本地改动
        subprocess.run(['git', 'stash', 'pop'], check=False, cwd=DATA_DIR, env=git_env,
                       creationflags=cf, capture_output=True)
    except Exception as e:
        print(f'[GIT] Sync failed: {e}', file=sys.stderr)
    
    # 兜底扫描：修复 git sync 残留的冲突标记
    _fix_corrupted_jsons()

    print(f'=== CS2 Dashboard Update ({mode}) ===')

    # ── Update ECO prices → holdings.json ──
    if mode in ('all', 'prices'):
        holdings_path = os.path.join(DATA_DIR, 'holdings.json')
        holdings = read_json(holdings_path)

        items = holdings.get('items', [])
        hash_names = [it['market_hash'] for it in items if it.get('market_hash')]
        print(f'[ECO] Fetching prices for {len(hash_names)} items...')

        prices = fetch_eco_prices(hash_names)
        print(f'[ECO] Got {len(prices)} prices')

        updated = 0
        today = time.strftime('%Y-%m-%d')
        for item in items:
            hn = item.get('market_hash')
            if hn and hn in prices:
                new_price = prices[hn]
                old_price = item.get('price', 0)

                # 更新价格
                item['price'] = new_price
                updated += 1

                # 记录历史价格（用于计算涨跌率）
                history = item.get('price_history', [])

                # 如果今天已有记录，更新；否则追加
                found = False
                for h in history:
                    if h.get('date') == today:
                        h['price'] = new_price
                        found = True
                        break
                if not found:
                    history.append({'date': today, 'price': new_price})

                # 保留最近 60 天历史（足够算 rate_30）
                history.sort(key=lambda x: x['date'])
                item['price_history'] = history[-60:]

                # 计算涨跌率
                # rate_1: 相对上一次更新
                if old_price and old_price > 0:
                    item['rate_1'] = round((new_price - old_price) / old_price * 100, 2)
                else:
                    item['rate_1'] = 0

                # rate_7: 相对 7 天前
                hist = item['price_history']
                if len(hist) >= 2:
                    # 找 7 天前的记录
                    today_dt = time.strptime(today, '%Y-%m-%d')
                    for h in hist:
                        h_dt = time.strptime(h['date'], '%Y-%m-%d')
                        days_diff = (time.mktime(today_dt) - time.mktime(h_dt)) / 86400
                        if 6 <= days_diff <= 8 and h.get('price', 0) > 0:
                            item['rate_7'] = round((new_price - h['price']) / h['price'] * 100, 2)
                            break
                    else:
                        # 没找到 7 天前的，用最旧的记录估算
                        if hist[0].get('price', 0) > 0:
                            oldest = hist[0]
                            oldest_dt = time.strptime(oldest['date'], '%Y-%m-%d')
                            days = max(1, (time.mktime(today_dt) - time.mktime(oldest_dt)) / 86400)
                            rate_raw = (new_price - oldest['price']) / oldest['price'] * 100
                            # 归一化到 7 天
                            item['rate_7'] = round(rate_raw / days * 7, 2) if days > 0 else 0

                # rate_30: 相对 30 天前（同理）
                if len(hist) >= 2:
                    today_dt = time.strptime(today, '%Y-%m-%d')
                    for h in hist:
                        h_dt = time.strptime(h['date'], '%Y-%m-%d')
                        days_diff = (time.mktime(today_dt) - time.mktime(h_dt)) / 86400
                        if 28 <= days_diff <= 32 and h.get('price', 0) > 0:
                            item['rate_30'] = round((new_price - h['price']) / h['price'] * 100, 2)
                            break
                    else:
                        # 没找到 30 天前的，用最旧的记录估算
                        if hist[0].get('price', 0) > 0:
                            oldest = hist[0]
                            oldest_dt = time.strptime(oldest['date'], '%Y-%m-%d')
                            days = max(1, (time.mktime(today_dt) - time.mktime(oldest_dt)) / 86400)
                            rate_raw = (new_price - oldest['price']) / oldest['price'] * 100
                            # 归一化到 30 天
                            item['rate_30'] = round(rate_raw / days * 30, 2) if days > 0 else 0

        total_cost = sum(it.get('cost', 0) * it.get('qty', 1) for it in items)
        total_market = sum(it.get('price', 0) * it.get('qty', 1) for it in items)
        holdings['total_cost'] = round(total_cost, 2)
        holdings['total_market'] = round(total_market, 2)
        holdings['update_time'] = time.strftime('%Y-%m-%d %H:%M:%S')

        write_json(holdings_path, holdings)

        pnl = total_market - total_cost
        pnl_pct = pnl / total_cost * 100 if total_cost else 0
        print(f'[ECO] Updated {updated}/{len(hash_names)} | Cost={total_cost:.0f} Market={total_market:.0f} PnL={pnl:+.0f} ({pnl_pct:+.1f}%)')

    # ── Update SteamDT BUFF prices → merge into holdings.json ──
    buff_prices = {}
    if mode in ('all', 'prices') and STEAM_KEY:
        print('[SteamDT] Fetching BUFF prices...')
        try:
            buff_prices = fetch_steamdt_prices(hash_names)
            if buff_prices:
                # Merge BUFF prices into holdings items
                for item in items:
                    hn = item.get('market_hash')
                    if hn and hn in buff_prices:
                        bp = buff_prices[hn]
                        item['buff_sell'] = bp.get('buff_sell', 0)
                        item['buff_buy'] = bp.get('buff_buy', 0)
                        item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                        item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                write_json(holdings_path, holdings)
                print(f'[SteamDT] Merged BUFF prices for {len(buff_prices)} items into holdings')

            # ── 同时合并多平台价格到 eco_tracked.json ──
            eco_path = os.path.join(DATA_DIR, 'eco_tracked.json')
            eco_items = read_json(eco_path)
            if isinstance(eco_items, list) and eco_items:
                merged = 0
                for item in eco_items:
                    hn = item.get('HashName', '')
                    if hn and hn in buff_prices:
                        bp = buff_prices[hn]
                        item['buff_sell'] = bp.get('buff_sell', 0)
                        item['buff_buy'] = bp.get('buff_buy', 0)
                        item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                        item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                        item['buff_source'] = bp.get('buff_source', '')
                        item['platforms'] = bp.get('platforms', {})
                        merged += 1
                write_json(eco_path, eco_items)
                print(f'[SteamDT] Merged multi-platform prices for {merged}/{len(eco_items)} items into eco_tracked.json')
        except Exception as e:
            print(f'[SteamDT] BUFF prices failed: {e}', file=sys.stderr)

    # ── Compute self-alerts from BUFF price history → market.json ──
    alerts_data = []
    if mode in ('all', 'alerts'):
        print('[ALERTS] Computing from BUFF price history...')
        try:
            if buff_prices:
                alerts_data = compute_alerts(buff_prices)
            if alerts_data:
                print(f'[ALERTS] Got {len(alerts_data)} alerts')
                market_path = os.path.join(DATA_DIR, 'market.json')
                market = read_json(market_path)
                market['alerts'] = alerts_data
                market['alerts_updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                write_json(market_path, market)
            else:
                print('[ALERTS] No history data yet, skipping alerts')
        except Exception as e:
            print(f'[ALERTS] Failed: {e}', file=sys.stderr)

    # ── Update SteamDT K-lines (optional) ──
    if mode in ('all', 'klines') and STEAM_KEY:
        print('[SteamDT] Fetching K-lines...')
        try:
            market_path = os.path.join(DATA_DIR, 'market.json')
            market = read_json(market_path)
            # 从 holdings.json 读取物品列表（market.json 的 items 可能为空对象）
            holdings_path = os.path.join(DATA_DIR, 'holdings.json')
            holdings = read_json(holdings_path)
            items_list = holdings.get('items', [])
            print(f'[SteamDT] Items list: {len(items_list)} items (from holdings.json)')
            kline_data = fetch_steamdt_klines(items_list)
            print(f'[SteamDT] K-line data: {len(kline_data)} items fetched')
            if kline_data:
                for item in items_list:
                    name = item.get('name_en') or item.get('name', '')
                    if name in kline_data:
                        item['kline'] = kline_data[name]
                market['items'] = items_list
                write_json(market_path, market)
        except Exception as e:
            print(f'[SteamDT] K-lines failed: {e}', file=sys.stderr)


    # ── Update Steam News → news.json ──
    if mode in ('all',):
        print('[NEWS] Fetching CS2 Steam news...')
        try:
            news_data = fetch_steam_news()
            if news_data:
                news_path = os.path.join(DATA_DIR, 'news.json')
                write_json(news_path, news_data)
        except Exception as e:
            print(f'[NEWS] Failed: {e}', file=sys.stderr)

    # ── ECO Catalog (full item data, excludes knives/statrak) ──
    # Start catalog build in background early so it runs in parallel with other steps
    _catalog_future = None
    if mode in ('all', 'eco'):
        print('[ECO] Building catalog (parallel background)...')
        try:
            # 备份带BUFF数据的旧文件，防止CSQAQ失败后丢失平台数据
            tracked_path_bak = os.path.join(DATA_DIR, 'eco_tracked.json')
            if os.path.exists(tracked_path_bak):
                shutil.copy2(tracked_path_bak, tracked_path_bak + '.bak')
            _catalog_executor = ThreadPoolExecutor(max_workers=1)
            _catalog_future = _catalog_executor.submit(eco_catalog.build)
        except Exception as e:
            print(f'[ECO] Failed to start catalog: {e}', file=sys.stderr)

    # ── Generate Recommendations (dual ECO/BUFF scoring from catalog) ──
    if mode in ('all', 'alerts'):
        # Wait for catalog build to finish before generating recommendations
        if _catalog_future is not None:
            print('[REC] Waiting for catalog build...')
            try:
                _catalog_future.result()
                print('[REC] Catalog ready, generating recommendations')
            except Exception as e:
                print(f'[REC] Catalog failed: {e}', file=sys.stderr)

        # ── CSQAQ + SteamDT 综合多平台数据 ──
        # 目标：让全量饰品都有价格数据
        try:
            tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
            tracked = read_json(tracked_path) if os.path.exists(tracked_path) else []
            if not isinstance(tracked, list):
                tracked = []

            if tracked:
                # 1. CSQAQ 排行榜（200件，最快，含涨跌率）
                csqaq_alerts = recommend.fetch_csqaq_alerts()
                if csqaq_alerts:
                    csqaq_map = {}
                    for a in csqaq_alerts:
                        csqaq_map[a['name']] = a
                    merged = 0
                    for item in tracked:
                        hn = item.get('HashName', '')
                        if hn and hn in csqaq_map:
                            ca = csqaq_map[hn]
                            if ca.get('price', 0) > 0:
                                item['buff_sell'] = ca['price']
                                item['buff_source'] = 'BUFF'
                            item['buff_buy'] = ca.get('buff_buy_price', 0) or item.get('buff_buy', 0)
                            item['buff_sell_num'] = ca.get('buff_sell', 0) or item.get('buff_sell_num', 0)
                            item['buff_buy_num'] = ca.get('buff_buy', 0) or item.get('buff_buy_num', 0)
                            merged += 1
                    print(f'[CSQAQ] Rank list merged: {merged} items')

                # 2. CSQAQ 全量查价（每次更新重新扫描所有饰品，保证数据最新）
                all_hashnames = [it['HashName'] for it in tracked if it.get('HashName')]
                if all_hashnames:
                    print(f'[CSQAQ] Full scan: {len(all_hashnames)} items...')
                    batch_prices = recommend.fetch_csqaq_batch_prices(all_hashnames)
                    if batch_prices:
                        merged = 0
                        for item in tracked:
                            hn = item.get('HashName', '')
                            if hn and hn in batch_prices:
                                bp = batch_prices[hn]
                                if bp.get('buff_sell', 0) > 0:
                                    item['buff_sell'] = bp['buff_sell']
                                    item['buff_source'] = 'BUFF'
                                item['buff_sell_num'] = bp.get('buff_sell_num', 0) or item.get('buff_sell_num', 0)
                                item['yyyp_sell'] = bp.get('yyyp_sell', 0)
                                item['yyyp_sell_num'] = bp.get('yyyp_sell_num', 0)
                                merged += 1
                        print(f'[CSQAQ] Batch merged: {merged} items')
                        # ── CSQAQ 全量数据 → 保存到 buff_history（秒级完成，无批次限制）──
                        if batch_prices and len(batch_prices) > 100:
                            try:
                                save_buff_history(batch_prices)
                                print(f'[HISTORY] Saved {len(batch_prices)} items from CSQAQ to buff_history.json')
                            except Exception as e:
                                print(f'[HISTORY] CSQAQ save failed: {e}', file=sys.stderr)

                # 自动检测：BUFF/YYYP 覆盖率过低时保留旧数据
                if merged > 0 and merged < len(tracked) * 0.5:
                    print(f'[CSQAQ] [!]️ 覆盖率仅 {merged/len(tracked)*100:.0f}%（<50%），尝试恢复备份！')
                    # 尝试从备份恢复（.bak 是build前备份的带BUFF数据的老文件）
                    bak_path = tracked_path + '.bak'
                    if os.path.exists(bak_path):
                        tracked_old = read_json(bak_path)
                        if tracked_old:
                            old_buff = sum(1 for it in tracked_old if (it.get('buff_sell', 0) or 0) > 0)
                            if old_buff > merged:
                                print(f'[CSQAQ] 恢复备份：{old_buff} 件BUFF价格 > 新数据 {merged} 件')
                                tracked = tracked_old
                            else:
                                write_json(tracked_path, tracked)
                        else:
                            write_json(tracked_path, tracked)
                    else:
                        write_json(tracked_path, tracked)
                else:
                    write_json(tracked_path, tracked)
                # 清理备份文件
                bak_path = tracked_path + '.bak'
                if os.path.exists(bak_path):
                    os.remove(bak_path)

                # ── 兜底：从 buff_history.json 回填 BUFF/YY 价格 ──
                if merged < len(tracked) * 0.5:
                    print(f'[CSQAQ] 覆盖率低 ({merged}/{len(tracked)})，启动 buff_history 回填...')
                    merge_buff_history_to_tracked()

            # 3. SteamDT 补充（持仓32件 + 部分全量）
            if STEAM_KEY:
                try:
                    holdings_path = os.path.join(DATA_DIR, 'holdings.json')
                    holdings = read_json(holdings_path)
                    h_items = holdings.get('items', [])
                    hn_list = [it['market_hash'] for it in h_items if it.get('market_hash')]
                    if hn_list:
                        print(f'[SteamDT] Updating {len(hn_list)} holdings...')
                        sp = fetch_steamdt_prices(hn_list, verbose=False)
                        if sp:
                            for item in h_items:
                                hn = item.get('market_hash', '')
                                if hn in sp:
                                    bp = sp[hn]
                                    item['buff_sell'] = bp.get('buff_sell', 0)
                                    item['buff_buy'] = bp.get('buff_buy', 0)
                                    item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                    item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                            write_json(holdings_path, holdings)
                            print(f'[SteamDT] Holdings updated: {len(sp)} items')
                except Exception as e:
                    print(f'[SteamDT] Holdings update failed: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[MultiPrice] Failed: {e}', file=sys.stderr)

        # ── 用全量追踪数据获取多平台价格（SteamDT）──
        # 之前 prices 分支只查了持仓的 32 件，现在 eco_tracked.json 已建好
        # 拿全量 hash_names 去查，让 5000+ 件都有 BUFF/悠悠/C5/IGXE 价格
        try:
            tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
            if os.path.exists(tracked_path) and STEAM_KEY:
                tracked = read_json(tracked_path)
                if isinstance(tracked, list) and len(tracked) > len(buff_prices):
                    all_hn = [it['HashName'] for it in tracked if it.get('HashName')]
                    print(f'[SteamDT] Fetching multi-platform prices for {len(all_hn)} tracked items...')
                    full_prices = fetch_steamdt_prices(all_hn, verbose=False)
                    if full_prices and len(full_prices) > len(buff_prices):
                        buff_prices = full_prices  # 用全量数据替换
                        # 合并到 eco_tracked.json
                        merged = 0
                        for item in tracked:
                            hn = item.get('HashName', '')
                            if hn and hn in full_prices:
                                bp = full_prices[hn]
                                item['buff_sell'] = bp.get('buff_sell', 0)
                                item['buff_buy'] = bp.get('buff_buy', 0)
                                item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                                item['platforms'] = bp.get('platforms', {})
                                merged += 1
                        write_json(tracked_path, tracked)
                        print(f'[SteamDT] Merged {merged}/{len(tracked)} items (full catalog + platforms)')
                        
                        # ── 用全量数据保存 BUFF 历史快照 ──
                        if buff_prices and len(buff_prices) > 0:
                            try:
                                save_buff_history(buff_prices)
                                print(f'[HISTORY] Saved {len(buff_prices)} items to buff_history.json')
                            except Exception as e:
                                print(f'[HISTORY] Save failed: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[SteamDT] Full-catalog fetch failed: {e}', file=sys.stderr)
        try:
            recs = generate_recommendations(alerts=alerts_data, steamdt_prices=buff_prices)
            total = len(recs.get('all', []))
            eco_n = sum(1 for r in recs.get('all', []) if r.get('tag') == 'eco')
            buff_n = sum(1 for r in recs.get('all', []) if r.get('tag') == 'buff')
            print(f'[REC] {total} recommendations (ECO={eco_n}, BUFF={buff_n})')

            market_path = os.path.join(DATA_DIR, 'market.json')
            market = read_json(market_path)
            market['recommendations'] = recs
            write_json(market_path, market)

            # ── 保存每日推荐到追踪数据（累积历史，供AI分析涨跌根因）──
            try:
                import tracking_ai
                n = tracking_ai.save_daily_tracks(recs.get('all', []))
                if n > 0:
                    dirty_files.add('rec_tracks.json')
            except Exception as e:
                print(f'[TRACK-AI] Save failed (non-fatal): {e}', file=sys.stderr)

            # ── Record price history for ALL tracked items (SQLite) ──
            try:
                import price_db
                # 首次运行自动从历史数据种子DB，避免图表数据稀疏
                _seed_db_if_needed(price_db)
                tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
                if os.path.exists(tracked_path):
                    tracked = read_json(tracked_path)
                    now = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())
                    records = []
                    recorded = 0
                    for it in tracked:
                        hn = it.get('HashName', '')
                        if not hn:
                            continue
                        eco_p = float(it.get('Price', 0) or 0)
                        if eco_p > 0:
                            records.append((hn, 'eco', now, eco_p))
                            recorded += 1
                        multi_p = float(it.get('buff_sell', 0) or 0)
                        if multi_p > 0:
                            records.append((hn, 'buff', now, multi_p))
                        yyyp_p = float(it.get('yyyp_sell', 0) or 0)
                        if yyyp_p > 0:
                            records.append((hn, 'yy', now, yyyp_p))
                    # 批量写入 SQLite
                    written = price_db.record_batch(records)
                    print(f'[PRICE_HIST] SQLite: {written} records for {recorded}/{len(tracked)} items')
                    # 定期修剪旧数据（保留90天）
                    price_db.trim_old_data(90)
                    # Inject price history from SQLite into rec items
                    for r in recs.get('all', []):
                        hn = r.get('hash_name', '')
                        if not hn: continue
                        try:
                            history = price_db.get_history(hn, channel='eco')
                            if history:
                                r['eco_history'] = [h['price'] for h in history[-60:]]
                            history = price_db.get_history(hn, channel='buff')
                            if history:
                                r['multi_history'] = [h['price'] for h in history[-60:]]
                            history = price_db.get_history(hn, channel='yy')
                            if history:
                                r['yyyp_history'] = [h['price'] for h in history[-60:]]
                        except:
                            pass
                    # Re-write market.json with history injected
                    market['recommendations'] = recs
                    # Include tracked item names for frontend autocomplete
                    name_set = set()
                    for it in tracked:
                        hn = it.get('HashName', '') or ''
                        gn = it.get('GoodsName', '') or ''
                        if hn: name_set.add(hn)
                        if gn: name_set.add(gn)
                    market['eco_tracked_names'] = sorted(name_set)[:3000]  # 前端只用到前3000
                    write_json(market_path, market)
                    print(f'[PRICE_HIST] Recorded ECO prices for {recorded}/{len(tracked)} items')
            except Exception as e:
                print(f'[PRICE_HIST] Failed: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[REC] Failed: {e}', file=sys.stderr)

    # ── Steam Market full item list + recommendations (replaces ECO) ──
    if mode in ('all', 'market'):
        if _check_host_blocked('steamcommunity.com'):
            print('[MARKET] Skipped (steamcommunity.com blocked by hosts file)')
        else:
            print('[MARKET] Fetching Steam Market items...')
            try:
                items = sm.fetch_steam_market_items(max_items=200, min_price=5.0, max_pages=15)
                
                # Fetch BUFF prices via SteamDT for market items
                if STEAM_KEY:
                    market_hash_names = [it['name_en'] for it in items if it.get('name_en')]
                    if market_hash_names:
                        print(f'[MARKET] Fetching BUFF prices for {len(market_hash_names)} items (SteamDT)...')
                        smdt_prices = fetch_steamdt_prices(market_hash_names)
                        if smdt_prices:
                            for it in items:
                                hn = it.get('name_en', '')
                                if hn in smdt_prices:
                                    bp = smdt_prices[hn]
                                    it['buff_sell'] = bp.get('buff_sell', 0)
                                    it['buff_buy'] = bp.get('buff_buy', 0)
                                    it['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                    it['buff_buy_num'] = bp.get('buff_buy_num', 0)
                            print(f'[MARKET] Merged BUFF prices for {len(smdt_prices)} items')
                
                hp = os.path.join(DATA_DIR, 'market_history.json')
                history = sm.update_market_history(items, hp)
                alerts = sm.compute_alerts_from_history(history)
                recs = sm.generate_recommendations(alerts, items)

                # Write to market.json
                market_path = os.path.join(DATA_DIR, 'market.json')
                market = read_json(market_path)
                market['steam_market_items'] = len(items)
                # Don't overwrite REC's dual-channel recommendations
                if 'recommendations' not in market:
                    market['recommendations'] = recs
                market['steam_market_recs'] = recs
                market['market_updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                write_json(market_path, market)
                print(f'[MARKET] Done: {len(items)} items, saved to market.json')
            except Exception as e:
                print(f'[MARKET] Failed: {e}', file=sys.stderr)

    # ── 同步生成全市场扫描快照 ──
    try:
        import generate_scan
        generate_scan.main()
        dirty_files.add('market_scan.json')
        print('[SCAN] market_scan.json regenerated')
    except Exception as e:
        print(f'[SCAN] generate_scan failed: {e}', file=sys.stderr)

    # ── 同步生成关联分析数据 ──
    try:
        import generate_correlation
        generate_correlation.main()
        dirty_files.add('correlation_data.json')
    except Exception as e:
        print(f'[CORR] generate_correlation failed: {e}', file=sys.stderr)

    # ── 生成完整中文名映射（所有物品）──
    try:
        import_namejs = lambda d: os.path.join(d)
        eco_cat_path = os.path.join(DATA_DIR, 'eco_catalog.json')
        name_map_path = os.path.join(DATA_DIR, 'name_map.json')
        catalog = json.load(open(eco_cat_path, 'r', encoding='utf-8'))
        name_map = {}
        for x in catalog:
            if x.get('HashName') and x.get('GoodsName'):
                name_map[x['HashName']] = x['GoodsName']
        json.dump(name_map, open(name_map_path, 'w', encoding='utf-8'), ensure_ascii=False)
        dirty_files.add('name_map.json')
        print(f'[NAME] Generated name_map.json: {len(name_map)} items')
    except Exception as e:
        print(f'[NAME] name_map generation skipped: {e}', file=sys.stderr)

    # ── 同步生成日报（每天一次）──
    try:
        report_path = os.path.join(DATA_DIR, 'daily_report.json')
        need_regenerate = True
        if os.path.exists(report_path):
            try:
                old = json.load(open(report_path, encoding='utf-8'))
                if old.get('date') == time.strftime('%Y-%m-%d'):
                    need_regenerate = False
            except: pass
        if need_regenerate:
            import generate_report
            generate_report.main()
            dirty_files.add('daily_report.json')
    except Exception as e:
        print(f'[REPORT] generate_report failed: {e}', file=sys.stderr)

    # ── 同步生成数据状态摘要 ──
    try:
        import json
        status_summary = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        # price_history (SQLite) dates
        try:
            import price_db
            stats = price_db.get_stats()
            status_summary['price_db'] = {
                'records': stats['total_records'],
                'items': stats['total_items'],
                'first': stats['first_ts'],
                'last': stats['last_ts'],
                'size_mb': stats['db_size_mb']
            }
        except:
            pass
        # buff_history dates
        bh_path = os.path.join(DATA_DIR, 'buff_history.json')
        if os.path.exists(bh_path):
            bh = json.load(open(bh_path, encoding='utf-8'))
            b_dates = sorted(bh.keys())
            status_summary['buff_history'] = {
                'count': len(b_dates),
                'first': b_dates[0] if b_dates else '',
                'last': b_dates[-1] if b_dates else '',
            }
        # file sizes/timestamps
        for fn in ['eco_tracked.json','holdings.json','market.json','price_summary.json']:
            fp = os.path.join(DATA_DIR, fn)
            if os.path.exists(fp):
                st = os.stat(fp)
                status_summary[fn] = {'size': st.st_size, 'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}
        out = os.path.join(DATA_DIR, 'data_status.json')
        json.dump(status_summary, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
        dirty_files.add('data_status.json')
        print(f'[STATUS] Summary generated: {len(status_summary)} fields')
    except Exception as e:
        print(f'[STATUS] Summary failed: {e}', file=sys.stderr)

    # ── 更新时间戳 ──
    market_path = os.path.join(DATA_DIR, 'market.json')
    if os.path.exists(market_path):
        try:
            m = read_json(market_path)
            if m and isinstance(m, dict):
                ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                m['updated'] = ts
                # 同步更新 alerts_updated（如果 alerts 分支没跑，这里兜底）
                if not m.get('alerts_updated'):
                    m['alerts_updated'] = ts
                write_json(market_path, m)
                print(f'[META] market.json updated -> {ts}')
        except Exception as e:
            print(f'[META] Failed to update market.json timestamp: {e}', file=sys.stderr)

    # ── 衍生 price_summary + AI 分析 ──
    generate_price_summary()
    
    # ═══════════════ AI 分析（限流保护：每次调用间隔≥8秒） ═══════════════
    _last_ai_call = [0]  # mutable for closure
    
    def _ai_call_with_rate_limit(func, name):
        """AI 调用限流保护：确保两次调用间隔 >= 8 秒，遇到 429 重试 3 次"""
        elapsed = time.time() - _last_ai_call[0]
        if elapsed < 8:
            wait = 8 - elapsed
            print(f'[AI] Rate limit wait {wait:.0f}s...')
            time.sleep(wait)
        for attempt in range(3):
            try:
                func()
                _last_ai_call[0] = time.time()
                return
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = (attempt + 1) * 10
                    print(f'[AI] {name} 429 rate limited, waiting {wait}s (attempt {attempt+1}/3)...')
                    time.sleep(wait)
                else:
                    raise
            except Exception as e:
                print(f'[AI] {name} failed (non-fatal): {e}', file=sys.stderr)
                _last_ai_call[0] = time.time()
                return
        print(f'[AI] {name} failed after 3 retries (rate limit)', file=sys.stderr)
        _last_ai_call[0] = time.time()
    
    _ai_call_with_rate_limit(generate_ai_analysis, 'Analysis')
    _ai_call_with_rate_limit(generate_ai_daily_report, 'Daily report')
    _ai_call_with_rate_limit(generate_ai_anomaly, 'Anomaly')
    _ai_call_with_rate_limit(generate_ai_stock_picks, 'Stock picks')
    _ai_call_with_rate_limit(generate_ai_market_insight, 'Market insight')
    _ai_call_with_rate_limit(generate_ai_news_impact, 'News impact')
    _ai_call_with_rate_limit(generate_ai_recommendations, 'Recommendations')

    # ── 追踪AI分析：深度分析推荐涨跌根因 + 提炼教训（数据量>=3条时）──
    try:
        import tracking_ai
        analysis = tracking_ai.main()  # 从 rec_tracks.json 加载全量追踪
        if analysis:
            dirty_files.add('tracking_analysis.json')
            dirty_files.add('tracking_lessons.json')
            print('[TRACK-AI] ✨ 分析完成，教训已积累')
    except Exception as e:
        print(f'[TRACK-AI] Failed (non-fatal): {e}', file=sys.stderr)

    # ── Push all dirty files at once ──
    push_all()

    print('=== Done ===')

if __name__ == '__main__':
    main()
