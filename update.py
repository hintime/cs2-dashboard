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

# ── git safe.directory：GitHub Actions self-hosted runner 以 SYSTEM 身份运行，
#    而 runner 工作目录（C:\actions-runner\_work\...）归交互用户所有，
#    git >= 2.35.2 会因此报 "detected dubious ownership in repository" 并中止。
#    safe.directory 属于安全配置，git 会无视仓库本地配置，因此只能走
#    环境变量通道（与命令行 -c 同优先级，且对整个进程树生效）。
#    （系统级 gitconfig 需管理员权限，此处避免依赖。）
if not os.environ.get('GIT_CONFIG_COUNT'):
    os.environ['GIT_CONFIG_COUNT'] = '1'
    os.environ['GIT_CONFIG_KEY_0'] = 'safe.directory'
    os.environ['GIT_CONFIG_VALUE_0'] = '*'
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eco_sign import get_eco_key, sign_eco
import steam_market as sm
import eco_catalog
import recommend  # CSQAQ multi-platform price provider

# ═══════════════ CONFIG ═══════════════
# ── 本地密钥文件（不入 git）：每行 KEY=VALUE，供本机运行时使用 ──
# 云端由 GitHub Actions Secrets 注入；本机读此文件，
# 避免把密钥写进代码（原明文默认值已于 2026-09-13 移除）。
_local_keys = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local_keys.env')
if os.path.exists(_local_keys):
    try:
        for _line in open(_local_keys, encoding='utf-8'):
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())
    except Exception as _e:
        print('[WARN] 读取 local_keys.env 失败: ' + str(_e))

PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
# CSQAQ removed — alerts now self-computed from BUFF price history
STEAM_KEY = os.environ.get('STEAMDT_KEY', '')


def _credential_manager_token():
    """从 Windows 凭据管理器取 GitHub token。

    本机（非 CI）环境下 GH_TOKEN / GITHUB_TOKEN 都没有，token 实际存在
    Windows 凭据管理器的 `git:https://github.com` 条目里（git-credential-manager
    写的）。原实现完全没读它，于是 `git_push_locally` 退回空 credential helper，
    push 一律 401 —— 数据在本机攒着、永远推不上去。
    """
    if sys.platform != 'win32':
        return ''
    try:
        import ctypes
        from ctypes import wintypes

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD),
                        ("Type", wintypes.DWORD),
                        ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                        ("Persist", wintypes.DWORD),
                        ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]

        advapi32 = ctypes.windll.advapi32
        advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                       wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        advapi32.CredReadW.restype = wintypes.BOOL
        pcred = ctypes.POINTER(CREDENTIAL)()
        if not advapi32.CredReadW("git:https://github.com", 1, 0, ctypes.byref(pcred)):
            return ''
        c = pcred.contents
        blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        advapi32.CredFree(pcred)
        # git-credential-manager 存的是 utf-16-le
        for enc in ('utf-16-le', 'utf-8', 'latin-1'):
            try:
                v = blob.decode(enc).strip('\x00').strip()
                if v:
                    return v
            except (UnicodeDecodeError, LookupError):
                continue
    except Exception as _e:
        print('[WARN] 读取 Windows 凭据管理器失败: ' + str(_e), file=sys.stderr)
    return ''


GH_TOKEN = (os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
            or _credential_manager_token())
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', '')
ZHIPU_KEY = os.environ.get('ZHIPU_KEY', '')
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'zhipu')  # 统一用智谱 GLM-4
REPO = 'hintime/cs2-dashboard'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..') if SCRIPT_DIR.endswith('.github') else SCRIPT_DIR

# ── git 非交互环境（本机/VPS/CI 通用）──
# 少了这几个环境变量，git 一旦需要凭据就会弹窗或直接挂住等输入。
GIT_ENV = {**os.environ,
           'GCM_INTERACTIVE': 'never',
           'GIT_TERMINAL_PROMPT': '0',
           'GIT_ASKPASS': 'echo'}
# git 公共参数：清掉 credential.helper（优先用显式 token），
# 并统一走 openssl backend + 关 SSL 校验（本机 hosts 走透明代理，证书链不完整）。
GIT_BASE = ['-c', 'credential.helper=', '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=false']

# 非 CI 环境下 GH_TOKEN 为空的告警（会导致 push 静默失败）
if not GH_TOKEN and not os.environ.get('GITHUB_ACTIONS'):
    print('[WARN] 未取到 GitHub token（env / Windows 凭据管理器均无），'
          '本次数据将无法推送', file=sys.stderr)

MAX_RETRIES = 3
RETRY_DELAY = 2

# ═══════════════ AI Provider 统一调度（zhipu 云 / ollama 本地）═══════════════
# 分工（可用环境变量覆盖）：
#   AI_PROVIDER_QUALITY  质量敏感任务（买入推荐、市场洞察）  默认取 AI_PROVIDER，再默认 zhipu
#   AI_PROVIDER_FAST     高频低价值任务（持仓/日报/异动/抄底/新闻） 默认同上
#   想让高频任务走本地：AI_PROVIDER_FAST=ollama（本地无需 key，离线免费）
#   OLLAMA_HOST / OLLAMA_MODEL / OLLAMA_NUM_CTX / ZHIPU_MODEL 均可覆盖
AI_PROVIDER_QUALITY = (os.environ.get('AI_PROVIDER_QUALITY') or os.environ.get('AI_PROVIDER') or 'zhipu')
AI_PROVIDER_FAST = (os.environ.get('AI_PROVIDER_FAST') or os.environ.get('AI_PROVIDER') or 'zhipu')
OLLAMA_HOST = (os.environ.get('OLLAMA_HOST') or 'http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL') or 'qwen2.5:7b-instruct'
OLLAMA_NUM_CTX = int(os.environ.get('OLLAMA_NUM_CTX') or '8192')
# 本地推理慢，且用户全局可能设了 OLLAMA_KEEP_ALIVE=0（每次调用都重载模型）→ 请求级覆盖
OLLAMA_KEEP_ALIVE = os.environ.get('OLLAMA_KEEP_ALIVE_PARAM') or '10m'
OLLAMA_TIMEOUT = int(os.environ.get('OLLAMA_TIMEOUT') or '600')      # 超时下限（秒）
OLLAMA_REASON_HEADROOM = float(os.environ.get('OLLAMA_REASON_HEADROOM') or '2.5')
ZHIPU_MODEL = os.environ.get('ZHIPU_MODEL') or 'glm-4-flash'
# 本地 Ollama 必须绕开系统/沙箱代理 —— 代理对 127.0.0.1 可能返回 502 Bad Gateway
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _ai_provider(quality=False):
    """按任务类别解析 provider：quality=True 质量敏感，False 高频低价值"""
    p = (AI_PROVIDER_QUALITY if quality else AI_PROVIDER_FAST) or 'zhipu'
    p = str(p).strip().lower()
    return p if p in ('zhipu', 'ollama') else 'zhipu'


def _ai_model_name(quality=False, model=None):
    if model and ':' in str(model):
        return model
    return ZHIPU_MODEL if _ai_provider(quality) == 'zhipu' else OLLAMA_MODEL


def _ai_provider_ready(quality=False):
    """zhipu 需要 key；ollama 不需要（可达性由实际调用报错暴露）"""
    return True if _ai_provider(quality) == 'ollama' else bool(ZHIPU_KEY)


def _is_reasoning_model(name):
    """推理模型（R1 / reasoner 等）会先产出思考 token，需为 num_predict 留余量"""
    n = str(name or '').lower()
    return any(k in n for k in ('r1', 'reason', 'thinking', 'qwq', 'o1'))


def _strip_think(t):
    """剥掉思考块：① <think>…</think> 成对块 ② DeepSeek-R1 专有 \uFF5C 竖线标记
    ③ 残留的“结束标记” → 丢弃它之前的全部内容（不同模型结束符不同，统一兜底）"""
    if not t:
        return t
    import re as _re
    t = _re.sub(r'<(think|thinking|reasoning)>[\s\S]*?</\1>', '', t, flags=_re.I)
    t = _re.sub(r'<[\uFF5C|]begin[^>]*thinking[\uFF5C|]>[\s\S]*?<[\uFF5C|]end[^>]*thinking[\uFF5C|]>', '', t)
    ends = list(_re.finditer(r'</(?:think|thinking|reason|reasoning)>|<[\uFF5C|]end[^>]*thinking[\uFF5C|]>', t, _re.I))
    if ends:
        t = t[ends[-1].end():]
    return t


def _strip_fence(t):
    """剥掉 markdown 代码围栏 —— 实测 deepseek-r1 即使在 format=json 下也会把 JSON 包进围栏"""
    if not t:
        return t
    s = t.strip()
    if s.startswith('```'):
        nl = s.find('\n')
        if nl > 0:
            s = s[nl + 1:]
        s = s.rstrip()
        if s.endswith('```'):
            s = s[:-3]
    return s.strip()


def _ai_parse_json(text):
    """容错解析 AI 输出的 JSON：直接 → 去围栏 → 截取首个 { 到末个 } / [ 到末个 ]"""
    if not text:
        return None
    t = _strip_think(text).strip()
    if not t:
        return None
    for cand in (t, _strip_fence(t)):
        try:
            return json.loads(cand)
        except Exception:
            pass
    for a, b in (('{', '}'), ('[', ']')):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                pass
    return None


def _ai_attempt(prov, mdl, messages, max_tokens, temperature, json_mode, timeout, tries=3):
    """单一 provider 的带重试调用；成功返回文本，失败返回 None"""
    for attempt in range(tries):
        try:
            if prov == 'ollama':
                # 推理模型的思考 token 也要从 num_predict 里扣 → 留足余量，否则 JSON 会被截断
                npred = max_tokens
                if _is_reasoning_model(mdl):
                    npred = min(16384, int(max_tokens * OLLAMA_REASON_HEADROOM) + 1024)
                body = {
                    'model': mdl, 'messages': messages, 'stream': False,
                    'keep_alive': OLLAMA_KEEP_ALIVE,   # 覆盖用户全局的 OLLAMA_KEEP_ALIVE=0
                    'options': {'temperature': temperature,
                                'num_ctx': OLLAMA_NUM_CTX,      # 默认 2048 会静默截断长 prompt，必须显式给
                                'num_predict': npred}
                }
                if json_mode:
                    body['format'] = 'json'
                req = urllib.request.Request(OLLAMA_HOST + '/api/chat',
                    data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                    headers={'Content-Type': 'application/json'})
                # 本地推理慢（7B 首次调用实测 60s+）→ 用超时下限，别沿用云端的 20~45s
                resp = _LOCAL_OPENER.open(req, timeout=max(timeout, OLLAMA_TIMEOUT))
                d = json.loads(resp.read().decode('utf-8', 'replace'))
                _c = _strip_think(((d.get('message') or {}).get('content') or '')).strip()
                return _strip_fence(_c) if json_mode else _c
            body = {'model': mdl, 'messages': messages,
                    'max_tokens': max_tokens, 'temperature': temperature}
            if json_mode:
                body['response_format'] = {'type': 'json_object'}
            req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions',
                data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                headers={'Authorization': 'Bearer ' + ZHIPU_KEY, 'Content-Type': 'application/json'})
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read().decode('utf-8', 'replace'))['choices'][0]['message'].get('content', '')
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = (attempt + 1) * 10
                print('[AI] %s 429 rate limited, waiting %ds...' % (prov, wait))
                time.sleep(wait)
            else:
                print('[AI] %s HTTP %d: %s' % (prov, e.code, str(e)[:120]), file=sys.stderr)
                if attempt == tries - 1:
                    return None
                time.sleep(3)
        except Exception as e:
            print('[AI] %s failed (attempt %d/%d, model=%s): %s'
                  % (prov, attempt + 1, tries, mdl, str(e)[:150]), file=sys.stderr)
            if attempt == tries - 1:
                return None
            time.sleep(3)
    return None


def _ai_call(messages, max_tokens=2048, temperature=0.5, json_mode=False,
             quality=False, timeout=90, model=None, provider=None):
    """统一 AI 出口 — 按 provider 分流，返回纯文本；失败返回 None。

    兜底链（2026-09-17 新增）：本地 ollama 不可用时，若配了 ZHIPU_KEY 就自动降级到云端。
    「本地优先、云端保底」——离线能跑，本地服务挂了也不至于让整条 AI 管线空转。
    关掉兜底：环境变量 AI_FALLBACK_CLOUD=0
    """
    # provider 显式指定时只走它（用于「强制云端复核」这类场景），不挂兜底链
    primary = (provider or _ai_provider(quality))
    chain = [primary]
    if (not provider and primary == 'ollama' and ZHIPU_KEY
            and str(os.environ.get('AI_FALLBACK_CLOUD', '1')).strip() != '0'):
        chain.append('zhipu')
    for idx, prov in enumerate(chain):
        if prov == 'zhipu' and not ZHIPU_KEY:
            print('[AI] 智谱未配置 ZHIPU_KEY，跳过该兜底')
            continue
        if idx == 0:
            if provider:
                mdl = model or (ZHIPU_MODEL if prov == 'zhipu' else OLLAMA_MODEL)
            else:
                mdl = _ai_model_name(quality, model)
            tmo = timeout
        else:
            mdl = ZHIPU_MODEL
            tmo = min(timeout, 120)      # 云端快，别沿用本地那 600s 的下限
            print('[AI] %s 不可用 → 降级到 %s(%s) 兜底' % (primary, prov, mdl))
        txt = _ai_attempt(prov, mdl, messages, max_tokens, temperature, json_mode, tmo)
        if txt is not None:
            return txt
    return None


def _ai_post(payload, quality=False, timeout=90):
    """传输层适配：按 provider 发送，回吐「智谱风格」dict，既有解析代码零改动"""
    txt = _ai_call(payload.get('messages') or [],
                   max_tokens=payload.get('max_tokens', 2048),
                   temperature=payload.get('temperature', 0.5),
                   json_mode=('response_format' in payload),
                   quality=quality, timeout=timeout, model=payload.get('model'))
    if txt is None:
        raise RuntimeError('AI 调用失败（provider=%s）' % _ai_provider(quality))
    return {'choices': [{'message': {'content': txt}}]}

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
    except Exception as _e:
        print(f'[WARN] 读取 hosts 文件失败: {_e}', file=sys.stderr)
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
        except Exception as _e:
            print(f'[WARN] 读取 buff_history 缓存失败: {_e}', file=sys.stderr)
    return {}

def save_buff_history(steamdt_prices):
    """Save hourly + daily BUFF/悠悠 snapshots to buff_history.json"""
    hour_key = time.strftime('%Y-%m-%dT%H:00')  # 小时级（异动）
    day_key = time.strftime('%Y-%m-%d')          # 日级（7日涨跌）
    history_file = os.path.join(DATA_DIR, 'buff_history.json')
    
    history = load_buff_history()
    
    # Keep last 12 hours + 15 days
    # 小时级从 48 降到 12：异动对比只需邻近时点，旧时点对功能无贡献，
    # 却让 buff_history.json 长期维持 50MB+ —— 每次提交都拖累 git 体积与前端加载。
    dates = sorted(history.keys(), reverse=True)
    keep = []
    for d in dates:
        if len(d) == 16 and len(keep) < 12:  # hourly: YYYY-MM-DDTHH:MM
            keep.append(d)
        elif len(d) == 10 and len(keep) < 12+15:  # daily: YYYY-MM-DD
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
                # ★ 独立市场基准价：Steam 社区市场。
                #   留在历史里，前端折线图才能画出「国内价 vs 独立市场」的交叉走势，
                #   而不是只能对比同样源的 BUFF/悠悠（价差常年 1-2%，看不出东西）。
                'steam_sell': info.get('steam_sell', 0),
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
    # 导出「前端精简版」（仅最近 12 个时点）——
    # 页面只需近期趋势，却以前要下载整份 50MB+ 的全量历史。
    try:
        recent_keys = sorted(history.keys())[-12:]
        buff_recent = {k: history[k] for k in recent_keys}
        write_json(os.path.join(DATA_DIR, 'buff_recent.json'), buff_recent)
        dirty_files.add('buff_recent.json')
        print(f'[HISTORY] buff_recent.json exported: {len(buff_recent)} snapshots')
    except Exception as e:
        print(f'[HISTORY] buff_recent export failed: {e}', file=sys.stderr)
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
# 推荐购买的在售量下限：低于此值不推荐（流动性差、出货难）。实测候选池中位在售量约 63 件，
# 卡 100 件后仍有 1305 件候选（33.9%），池子够用。可用 REC_MIN_SELLING=0 关闭该门槛。
REC_MIN_SELLING = int(os.environ.get('REC_MIN_SELLING') or '100')

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

def _rate_from_hist(hist, days):
    """从 price_history 序列算「相对 N 天前」的涨跌幅(%)。
    hist: [{'ts','price'}] 按时间升序。窗口内没有更早的采样点则返回 None（不硬凑）。"""
    if not hist or len(hist) < 2:
        return None
    import datetime as _dt
    def _p(ts):
        try:
            return _dt.datetime.fromisoformat(str(ts)[:19])
        except Exception:
            return None
    last_t = _p(hist[-1].get('ts'))
    if last_t is None:
        return None
    cutoff = last_t - _dt.timedelta(days=days)
    base = None
    for h in hist:
        t = _p(h.get('ts'))
        if t is None:
            continue
        if t <= cutoff:
            base = h.get('price')
        else:
            break
    if not base or base <= 0:
        return None
    cur = hist[-1].get('price') or 0
    if cur <= 0:
        return None
    return round((cur - base) / base * 100, 2)


def run_kronos_forecast(top_n=10, days=14, samples=3):
    """Kronos 批量价格预测：只预测「推荐池前 top_n 名」+「AI 精选」的标的。

    松耦合设计：子进程调用 cs2-kronos 的独立 venv（torch/transformers 依赖太重，
    不能混进主项目环境）。失败不影响主流程。
    关闭：环境变量 KRONOS_FORECAST=0
    """
    if str(os.environ.get('KRONOS_FORECAST', '1')).strip() == '0':
        return None
    venv_py = os.environ.get('KRONOS_PY') or r'C:\Users\Lenovo\cs2-kronos\venv\Scripts\python.exe'
    _local = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kronos_forecast.py')
    script = os.environ.get('KRONOS_SCRIPT') or (_local if os.path.exists(_local)
                                          else r'C:\Users\Lenovo\cs2-kronos\forecast_batch.py')
    if not (os.path.exists(venv_py) and os.path.exists(script)):
        print('[Kronos] 未找到独立环境（%s），跳过预测' % venv_py)
        return None
    env = dict(os.environ)
    # 剥掉 WorkBuddy 注入的 sitecustomize —— 其批量删除守卫会拦住 matplotlib 建字体缓存
    env.pop('PYTHONPATH', None)
    for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'FTP_PROXY'):
        env.pop(_k, None)
    out = os.path.join(DATA_DIR, 'ai_forecast.json')
    try:
        _t0 = time.time()
        r = subprocess.run(
            [venv_py, script, '--days', str(days), '--top', str(top_n),
             '--samples', str(samples), '--out', out],
            env=env, cwd=os.path.dirname(script), capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=1200, creationflags=0x08000000)
        if r.returncode == 0:
            print('[Kronos] 预测完成（%.0fs）→ ai_forecast.json' % (time.time() - _t0))
            return out
        print('[Kronos] 预测失败 rc=%d: %s' % (r.returncode, (r.stderr or '')[-160:]), file=sys.stderr)
    except Exception as e:
        print('[Kronos] 跳过（非致命）: %s' % str(e)[:140], file=sys.stderr)
    return None


def save_csqaq_boards(price_map):
    """把 CSQAQ 批量查价结果写入旁路文件 csqaq_boards.json（只存盘口/跨平台字段）。

    为什么单独存：eco_tracked.json 会被 prices 周期重写并清掉这些字段，
    而盘口/Steam 价查一次成本较高（96 批），不该每 30 分钟重查。
    """
    if not price_map:
        return 0
    path = os.path.join(DATA_DIR, 'csqaq_boards.json')
    boards = {}
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                boards = json.load(f)
        if not isinstance(boards, dict):
            boards = {}
    except Exception:
        boards = {}
    # ⚠ 2026-09-18：补 'platforms' —— 跨平台比价数据若不落旁路，会被 prices 周期重写清空。
    keys = ('buff_sell', 'buff_buy', 'buff_sell_num', 'buff_buy_num', 'buff_source',
            'yyyp_sell', 'yyyp_sell_num', 'steam_sell', 'steam_sell_num', '_csqaq_buff',
            'platforms')
    n = 0
    for hn, bp in price_map.items():
        if not isinstance(bp, dict):
            continue
        rec = {k: bp.get(k, 0) for k in keys if bp.get(k, 0)}
        if rec:
            # ⚠ 2026-09-18：原来整条替换（boards[hn]=rec）→ 后跑的 CSQAQ（只有卖侧）
            #   会把先前 SteamDT 写入的买盘字段覆盖掉。改为逐键合并，保两源并集。
            boards.setdefault(hn, {}).update(rec)
            n += 1
    try:
        write_json(path, boards)
        print('[CSQAQ] 盘口旁路已更新：%d 件（累计 %d 条）' % (n, len(boards)))
    except Exception as e:
        print('[CSQAQ] 盘口旁路写入失败: %s' % e, file=sys.stderr)
    return n


def generate_recommendations(alerts=None, steamdt_prices=None):
    """★ 权威推荐引擎（主看板 market.json:recommendations.all）。
    注意：steam_market.py 里另有一个同名函数，只服务 report.html 的「Steam 市场」小节
    （写入 market.json:steam_market_recs），两者口径独立、勿混用。"""
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

    # ── 盘口旁路文件 ──
    # prices 周期（每 30 分钟）会用新的 ECO 拉取结果重写 eco_tracked.json，只保留价格，
    # 会把 CSQAQ 查来的在售/求购量、悠悠盘口、Steam 价冲掉（2026-09-18 实测全池被清零）。
    # 因此盘口数据另存 csqaq_boards.json，每次读取时合并进来 —— 主文件被重写也不影响。
    _boards_path = os.path.join(DATA_DIR, 'csqaq_boards.json')
    if os.path.exists(_boards_path):
        try:
            with open(_boards_path, 'r', encoding='utf-8') as f:
                boards = json.load(f)
            if isinstance(boards, dict) and boards:
                _n = 0
                for _it in tracked:
                    _b = boards.get(_it.get('HashName', ''))
                    if isinstance(_b, dict):
                        _it.update(_b)
                        _n += 1
                print(f'[REC] 合并盘口旁路数据 {_n} 件（来自 csqaq_boards.json）')
        except Exception as _be:
            print(f'[REC] 读取盘口旁路失败: {_be}', file=sys.stderr)

    # 排除 StatTrak / Souvenir(纪念品) / BS(破损不堪/战痕累累) 等不想要的
    # ⚠ 2026-09-18 修复：ECO 真名以 "★ StatTrak™ " 开头（★ 前缀+空格），原 startswith
    #   ('StatTrak™ ', ...) 从未命中 → StatTrak 排除形同虚设（实测漏进候选池 3 件 ST 刀）。
    #   改为子串匹配；Souvenir 同理加固。
    _EXCLUDE_EXTERIORS = ('Battle-Scarred', '战痕累累', '破损不堪')
    before = len(tracked)
    tracked = [i for i in tracked
               if not any(k in (i.get('HashName','') + ' ' + i.get('GoodsName',''))
                          for k in ('StatTrak', 'Souvenir'))
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
                # ⚠ 2026-09-18：原来漏拷 platforms → rec 条目的 item.platforms 恒为空，
                #   前端「其他平台」比价区拿不到数据。
                'platforms': item.get('platforms', {}),
            }
    print(f'[REC] BUFF prices available for {len(buff_map)} items')

    # 稀有度映射：CSQAQ 排行榜返回 rarity_localized_name（ECO 侧没有该字段）
    # 没有该数据时 rarity_map 为空，前端只是不显示稀有度小标 —— 不虚构。
    rarity_map = {}
    try:
        for _a in (alerts or []):
            _n, _r = _a.get('name'), _a.get('rarity')
            if _n and _r:
                rarity_map[_n] = _r
    except Exception:
        pass

    # ── 接入归一化层（四源统一 + 交叉验证）──
    # normalize.py 把 ECO / SteamDT / CSQAQ / FirePulse 四个来源归一成统一字段，
    # 并算出真正可信的 ref_price（独立市场基准）与跨平台溢价。
    # 关键红线：基准必须来自「与 BUFF 非同源」的市场，否则溢价恒为 0（假指标）。
    _norm = None
    try:
        import normalize as _normalize
        _norm = _normalize
        print('[REC] normalize.py 已加载（四源归一化）')
    except Exception as _ne:
        print(f'[REC] normalize.py 加载失败，退回原始逻辑: {_ne}', file=sys.stderr)

    all_recs = []
    # 追踪教训权重：整轮只算一次（原实现放在循环内，4500 条 → 4500 次读文件）
    eco_mult, buff_mult = _get_scoring_weights_from_lessons()

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
        # 在售量下限：在售太少 → 流动性差、出货难 → 不进推荐池
        if selling < REC_MIN_SELLING:
            continue

        # ── 四源归一化：产出统一字段 + 可信溢价 ──
        # 就地回写 n_* 前缀字段，不污染原有字段，保证平滑接入。
        n_meta = None
        if _norm is not None:
            try:
                n_meta = _norm.apply_to_item(item)
            except Exception as _ne:
                n_meta = None

        # ══════════ 评分 v2（2026-09-17 重写）══════════
        # 旧版三个致命问题（实测导致全池 score 恒为 48.0、tag_label 全同一句）：
        #   ① 加分项用的是「BUFF/悠悠 相对 ECO 的溢价」——而 ECO 是**低位档参考价**，
        #      该溢价被系统性放大，每条都打满固定分（30+10=40 ×1.2 = 48.0）；
        #   ② final = max(eco, buff) 直接把 ECO 维度抹掉，分数由单一维度决定；
        #   ③ 无盘口数据时（bsn=0）后续分项全跳过，分数结构更固定。
        # 新版：每个维度只用**已验证口径**，各维度先归一化到 0-1 再按权重平均 →
        #       分数天然散开；缺数据的维度不参与（不虚增也不虚减）。
        import math as _m

        # ── 维度 A：ECO 盘口（固定满分，缺子项按中性 0.5 计）──
        import math as _m
        eco_reasons = []
        # A1 求购强度（30 分权重）：求购价/售价，0.75→0、1.0→满
        r_q = min(qg_max / price, 1.0) if (qg_max > 0 and price > 0) else None
        a1 = max(0.0, (r_q - 0.75) / 0.25) if r_q is not None else 0.5
        if r_q is not None and a1 * 30 >= 12:
            eco_reasons.append('求购价¥%.0f 达售价%.0f%%' % (qg_max, r_q * 100))
        # A2 求购单占比（25 分权重）
        if (selling + qg_total) > 0:
            tight = qg_total / (selling + qg_total)
            a2 = min(tight / 0.35, 1.0)
            if tight >= 0.15:
                eco_reasons.append('求购%d单/在售%d件' % (qg_total, selling))
        else:
            a2 = 0.5
        # A3 相对稀缺度（20 分权重）：以下限为 1.0、约 50 倍下限为 0 的对数刻度
        if selling > 0:
            _lo = max(REC_MIN_SELLING, 1)
            a3 = max(0.0, 1 - _m.log10(max(selling, _lo) / float(_lo)) / _m.log10(50.0))
            if selling <= _lo * 1.5:
                eco_reasons.append('ECO在售仅%d件（相对稀缺）' % selling)
        else:
            a3 = 0.5
        # A4 同口径估值折价（25 分权重）
        if compre > 0 and price > 0:
            d_val = (compre - price) / price * 100
            a4 = min(max(d_val, 0) / 15.0, 1.0)
            if d_val >= 8:
                eco_reasons.append('ECO综合价高于现价%.0f%%(¥%.0f vs ¥%.0f)' % (d_val, compre, price))
        else:
            a4 = 0.5
        eco_score_val = (a1 * 30 + a2 * 25 + a3 * 20 + a4 * 25) / 100.0
        eco_missing = ((1 if r_q is None else 0) + (1 if (selling + qg_total) <= 0 else 0)
                       + (1 if selling <= 0 else 0) + (1 if (compre <= 0 or price <= 0) else 0))

        # ── 维度 B：BUFF 盘口（固定满分；买盘缺失时 B1/B3 记中性 0.5，不虚增也不虚减）──
        buff_reasons = []
        bd = buff_map.get(hn, {}) or {}
        bs = bd.get('buff_sell', 0) or 0
        bb = bd.get('buff_buy', 0) or 0
        bsn = bd.get('buff_sell_num', 0) or 0
        bbn = bd.get('buff_buy_num', 0) or 0
        # B1 买卖盘强度（35 分权重）— 需买盘数据（当前全池缺失 → 恒中性）
        if bsn > 0 and bbn > 0:
            b1 = min((bbn / bsn) / 0.5, 1.0)
            buff_reasons.append('BUFF买%d单/卖%d单' % (bbn, bsn))
        else:
            b1 = 0.5
        # B2 在售深度（20 分权重）：约 100 件最佳
        b2 = max(0.0, 1 - abs(_m.log10(max(bsn, 1)) - 2) / 2.0) if bsn > 0 else 0.5
        # B3 买盘贴价（25 分权重）— 需买盘数据
        if bb > 0 and bs > 0:
            r_bb = bb / bs
            b3 = max(0.0, (r_bb - 0.8) / 0.2)
            if r_bb >= 0.9:
                buff_reasons.append('BUFF求购价达卖价%.0f%%' % (r_bb * 100))
        else:
            b3 = 0.5
        # B4 跨市场偏离（20 分权重）：dev=0 中立 0.5、±40 → 0/1
        dev = item.get('n_dev_steam')
        if isinstance(dev, (int, float)):
            b4 = min(max((dev + 40.0) / 80.0, 0.0), 1.0)
            if abs(dev) > 25:
                buff_reasons.append('Steam偏离%+.0f%%' % dev)
        else:
            b4 = 0.5
        buff_score_val = (b1 * 35 + b2 * 20 + b3 * 25 + b4 * 20) / 100.0
        buff_missing = ((0 if (bsn > 0 and bbn > 0) else 1) + (0 if bsn > 0 else 1)
                        + (0 if (bb > 0 and bs > 0) else 1) + (0 if isinstance(dev, (int, float)) else 1))

        # ── 维度 C：悠悠有品（固定满分 20；缺数据记中性）──
        yyyp_sell = item.get('yyyp_sell', 0) or 0
        yyyp_sell_num = item.get('yyyp_sell_num', 0) or 0
        y_reasons = []
        if yyyp_sell_num > 0:
            y_val = max(0.0, 1 - min(yyyp_sell_num, 500) / 500.0)
            if yyyp_sell_num < 50:
                y_reasons.append('悠悠在售仅%d件' % yyyp_sell_num)
        else:
            y_val = 0.5
        y_missing = 0 if yyyp_sell_num > 0 else 1

        # 维度权重（缺子项已在维度内按中性计，故此处不再需要"缺维度不参与"）
        _W = (('eco', 0.50 * eco_mult), ('buff', 0.35 * buff_mult), ('yy', 0.15))
        _vals = {'eco': eco_score_val, 'buff': buff_score_val, 'yy': y_val}
        final_score = round(sum(v * w for (k, w), v in zip(_W, _vals.values()))
                            / sum(w for _, w in _W) * 100, 1)
        # eco_score / buff_score 保持字段名（前端「评分构成」与 AI 都在用），统一为 0-100 归一值
        eco_score = round(eco_score_val * 100, 1)
        buff_score = round(buff_score_val * 100, 1)
        yyyp_score = round(y_val * 100, 1)

        if final_score < 25:
            continue

        # ── 主导维度 → tag（前端契约：tag ∈ {eco, buff}）──
        # ⚠ 2026-09-18：原来还要求 buff_reasons 非空，导致「买盘数据缺失 → 理由为空 →
        #   tag 恒为 eco」（前端 buff 分组事实消失，实测 30/30 全 eco）。改为纯按维度得分判定。
        if buff_score > eco_score:
            tag = 'buff'
            primary_reasons = (buff_reasons + eco_reasons[:1]) or eco_reasons
        else:
            tag = 'eco'
            primary_reasons = (eco_reasons + buff_reasons[:1]) or buff_reasons

        # ── 特征标签（替代旧版恒定的「多平台信号 ✓溢价强劲·AI优选」）──
        _feats = []
        if (selling + qg_total) > 0 and qg_total / (selling + qg_total) >= 0.20:
            _feats.append('求购活跃')
        # 卡了在售下限后「在售偏少」会条条命中、又变成模板 → 改为显示实际件数
        if selling >= 500:
            _feats.append('在售充裕·%d件' % selling)
        elif selling > 0:
            _feats.append('在售%d件' % selling)
        if isinstance(dev, (int, float)) and dev > 25:
            _feats.append('跨市场折价')
        if bsn > 0 and bbn > 0 and bbn / bsn >= 0.30:
            _feats.append('买盘强劲')
        if bsn >= 300:
            _feats.append('流动性充足')
        if yyyp_sell_num > 0 and yyyp_sell_num < 50:
            _feats.append('悠悠稀缺')
        if not _feats:
            _feats.append('多平台信号' if tag == 'buff' else 'ECO供需')
        display_tag = '·'.join(_feats[:3])
        if final_score >= 60:
            display_tag += ' · 优选'
        elif final_score >= 45:
            display_tag += ' · 可考虑'
        tag_label = display_tag
        lesson_signal = ''

        # ── 操作建议（同样剔除"相对 ECO 的溢价"这套假口径）──
        buy_advice_parts = []
        if (selling + qg_total) > 0:
            r_adv = qg_total / (selling + qg_total)
            bid = int(qg_max) if qg_max > 0 else int(price * 0.9)
            if r_adv >= 0.30:
                buy_advice_parts.append('买盘活跃，可挂求购价¥%d接货' % bid)
            elif r_adv >= 0.10:
                buy_advice_parts.append('供需偏紧，分批挂单建仓')
            else:
                buy_advice_parts.append('承接一般，建议小仓位试探')
        if isinstance(dev, (int, float)) and abs(dev) > 25:
            buy_advice_parts.append('Steam偏离%+.0f%%（国内%s）' % (dev, '更划算' if dev > 0 else '相对偏贵'))
        if bsn > 0:
            buy_advice_parts.append('BUFF在售%d件' % bsn)
        if not buy_advice_parts:
            buy_advice_parts.append('数据有限，建议小仓位试水')
        buy_advice = ' | '.join(buy_advice_parts[:2])

        # ── 理由一句话 + 教训钩子（这两个定义原本在被替换的区段内，这里补回）──
        combined_reason = ' | '.join(primary_reasons[:3]) if primary_reasons else ''
        reason_enhance = _get_reason_enhancements()

        reason = '{} | 综合{:.0f}(ECO{:.0f}/BUFF{:.0f}/悠悠{:.0f}) | {} | 💡 {} | 建议分仓操作,单品<10%'.format(
            display_tag, final_score, eco_score, buff_score, yyyp_score, combined_reason, buy_advice)

        
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
            # 存世量代理（ECO 在售总数）与稀有度（E:\ 无该源时为空）
            'n_supply': item.get('n_supply') or item.get('SellingTotal') or 0,
            # ⚠ 2026-09-18：fp_rarity 已移除 —— FirePulse 遗留字段，且唯一带稀有度的
            #   CSQAQ 排行榜对本池覆盖率仅 1/30（无有效来源），前端引用已同步清理。
            # ── 归一化层产出的统一字段（前端「数据来源」小标用）──
            'n_ref': item.get('n_ref', 0),
            'n_ref_src': item.get('n_ref_src', ''),
            'n_steam': item.get('n_steam', 0),
            # 真正的信号：相对 Steam/BUFF 常态比值(1.45)的异常偏离。
            # 直接看 premium_buff 永远是深负数（两个市场的结构性价差），
            # 只有 |dev|>25% 才是值得关注的异常。
            'n_dev_steam': item.get('n_dev_steam'),
            'n_premium_buff': item.get('n_premium_buff'),
            'n_premium_yyyp': item.get('n_premium_yyyp'),
            'n_cov': item.get('n_cov', 0),
            # 数据缺口（2026-09-18 新增）：各维度缺失的子项数（0=完整）
            'data_gaps': [k for k, n in (('eco', eco_missing), ('buff', buff_missing),
                                         ('yy', y_missing)) if n > 0],
            'n_warn': item.get('n_warn', []),
            '_reason': reason,
            '_cat': tag,
        })

    # Sort by combined score, take top 30
    all_recs.sort(key=lambda x: x['score'], reverse=True)
    # ⚠ 2026-09-18：同一饰品的不同磨损等级会互相挤占名额 —— 实测 30 条里 4 组重复、共占 9 条
    #   （如「沙漠之鹰|东方之谜」占 3 条），组合分散度差。加「同一基础饰品最多 N 档」限额。
    #   可用 REC_MAX_PER_SKIN 调整（0=关闭）。
    _max_per_skin = int(os.environ.get('REC_MAX_PER_SKIN') or '1')
    if _max_per_skin > 0:
        _seen, _picked, _overflow = {}, [], []
        for _r in all_recs:
            _base = (_r.get('name') or '').split(' (')[0].split('（')[0].strip()
            if _base and _seen.get(_base, 0) >= _max_per_skin:
                _overflow.append(_r)
                continue
            _seen[_base] = _seen.get(_base, 0) + 1
            _picked.append(_r)
        # 候选不足 30 时用被压制的条目按分数回补，保证数量不缩水
        all_recs = (_picked if len(_picked) >= 30 else (_picked + _overflow))[:30]
        _c = {}
        for _r in all_recs:
            _b = (_r.get('name') or '').split(' (')[0].split('（')[0].strip()
            _c[_b] = _c.get(_b, 0) + 1
        print('[REC] 分散度限额: 同饰品最多 %d 档 | 最终仍有 %d 组重复' % (_max_per_skin, sum(1 for v in _c.values() if v > 1)))
    else:
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
_STEAMDT_SLOT = os.path.join(DATA_DIR, '.steamdt_batch.slot')


def _steamdt_batch_slot(min_gap=62.0, wait_max=1800.0):
    """批量接口「每分钟 1 次」的**跨进程**互斥（官方文档 6369437）。

    2026-09-18 实测：daemon 的 all 周期与手动补数据脚本同时跑 →
    两个进程各自按 65s 间隔发批，实际每分钟发 2 次 → 双双 errorCode=4005。
    这里用文件时间戳"占坑"：谁先读到过期槽位谁占坑，其余等待，保证全机每分钟一次。
    """
    import time as _t
    t0 = _t.time()
    while True:
        last = 0.0
        try:
            with open(_STEAMDT_SLOT, 'r') as f:
                last = float((f.read() or '0').strip() or 0)
        except Exception:
            last = 0.0
        gap = _t.time() - last
        if gap >= min_gap:
            try:
                with open(_STEAMDT_SLOT, 'w') as f:
                    f.write(str(_t.time()))
            except Exception:
                pass
            return True
        if _t.time() - t0 > wait_max:
            return False
        _t.sleep(min(20.0, max(1.0, min_gap - gap)) + 0.3)


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
        # ⚠ 2026-09-18：原来只挑「最优平台」、其余全部丢弃 → 前端「其他平台」比价区块（12 处引用
        #   item.platforms）恒为空、该功能一直是死的。这里把同一次返回里的所有平台一并收集，
        #   零额外请求成本地激活跨平台比价（C5 / 悠悠 / WAXPEER / STEAM / BUFF 等）。
        plats = {}
        for p_inner in platforms:
            plat = p_inner.get('platform', '')
            sell = float(p_inner.get('sellPrice', 0) or 0)
            buy = float(p_inner.get('biddingPrice', 0) or 0)
            if sell <= 0 and buy <= 0:
                continue
            if plat:
                plats[plat] = {
                    'sell': sell,
                    'sell_num': int(p_inner.get('sellCount', 0) or 0),
                    'buy': buy,
                    'buy_num': int(p_inner.get('biddingCount', 0) or 0),
                }
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
        if best is not None and plats:
            best['platforms'] = plats
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
            except Exception as _e:
                if len(prices) < 3:
                    print(f'[WARN] SteamDT 拓价失败({name[:40]}): {_e}', file=sys.stderr)
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
            # ⚠ 2026-09-18：原实现只按批间隔 sleep 65s，但**多个进程**（daemon + 手动脚本）
            #   会同时抢这个"每分钟 1 次"的配额 → 双双 4005。改为跨进程占坑（见 _steamdt_batch_slot）。
            if not _steamdt_batch_slot():
                print('[SteamDT] 等待批量接口槽位超时，放弃本轮', file=sys.stderr)
                break
            body = _json.dumps({'marketHashNames': batch}).encode('utf-8')
            try:
                result = None
                # ⚠ 2026-09-18（依官方文档 6369437）：批量接口限「每分钟 1 次」，
                #   撞限流 errorCode=4005 时原来只打印一次 → 整个池子拿不到买盘。
                #   改为等 60s 重试（最多 3 次），把限流当"稍后再来"而不是"放弃"。
                for _attempt in range(3):
                    try:
                        resp = http_post_raw(
                            'https://open.steamdt.com/open/cs2/v1/price/batch',
                            body,
                            headers={'Authorization': f'Bearer {STEAM_KEY}', 'Content-Type': 'application/json'},
                            timeout=30,
                        )
                        # ⚠ 2026-09-18 真因：http_post_raw 文档明写 "Return parsed JSON"（内部已 json.loads），
                        #   这里再 _json.loads 一次必然抛 TypeError（dict 不是 str）→ 被裸 except 吞掉
                        #   → **批量取价从来没成功过**（全池买盘缺失的根因，比限流更根本）。
                        result = resp if isinstance(resp, dict) else _json.loads(resp)
                    except Exception as _be:
                        result = None
                        if verbose:
                            print('[SteamDT] batch %d 请求异常: %s' % (batch_idx + 1, str(_be)[:100]), file=sys.stderr)
                    if result and result.get('success'):
                        break
                    if verbose or _attempt == 0:
                        print('[SteamDT] batch %d 失败 errorCode=%s msg=%s → 等 60s 重试 (%d/3)'
                              % (batch_idx + 1, (result or {}).get('errorCode'),
                                 (result or {}).get('errorMsg'), _attempt + 1), file=sys.stderr)
                    time.sleep(60.0)
                batch_saved = 0
                if result and result.get('success'):
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
            except Exception as _e:
                print(f'[WARN] 翻译(主源)失败: {_e}', file=sys.stderr)
            # Fallback: Google Translate (may be blocked)
            try:
                turl = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=' + urllib.parse.quote(text[:200])
                resp = http_get(turl, timeout=20)
                if isinstance(resp, list) and len(resp) > 0 and isinstance(resp[0], list) and len(resp[0]) > 0:
                    translated = resp[0][0][0]
                    if translated and translated != text:
                        return translated
            except Exception as _e:
                print(f'[WARN] 翻译(备用源)失败: {_e}', file=sys.stderr)
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
    except Exception as _e:
        print(f'[WARN] 原子写入失败，回退直接写入: {_e}', file=sys.stderr)
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
    if not _ai_provider_ready(quality=False):
        print('[AI] 无可用 AI provider（智谱无 key 且未启用本地），跳过持仓分析')
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
    except Exception as _e:
        print(f'[WARN] 获取市场背景失败: {_e}', file=sys.stderr)

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
        r = _ai_post(json.loads(data.decode('utf-8')), quality=False, timeout=120)
        raw = r['choices'][0]['message']['content']
        
        # ③ 解析 JSON 响应（本地模型可能带 markdown 围栏 → 容错解析）
        parsed = _ai_parse_json(raw)
        if not parsed:
            raise ValueError('批量分析未返回可解析 JSON')
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
                rr = _ai_post(json.loads(data.decode('utf-8')), quality=False, timeout=20)
                item_result = _ai_parse_json(rr['choices'][0]['message']['content'])
                if not item_result:
                    raise ValueError('未返回可解析 JSON')
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
    if not _ai_provider_ready(quality=False): return
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
        r = _ai_post(json.loads(data.decode('utf-8')), quality=False, timeout=30)
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
    if not _ai_provider_ready(quality=False): return
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
        r = _ai_post(json.loads(data.decode('utf-8')), quality=False, timeout=20)
        result = {'anomalies': [{'name': n, 'pct': round(pct, 1)} for n, pct, _, _ in top], 'analysis': r['choices'][0]['message']['content']}
        write_json(os.path.join(DATA_DIR, 'ai_anomaly.json'), result)
        print(f'[AI] Anomaly analysis done ({len(top)} items)')
    except Exception as e:
        print(f'[AI] Anomaly failed: {e}')

def generate_ai_stock_picks():
    """AI 扫描全市场找低估品"""
    if not _ai_provider_ready(quality=False): return
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
        r = _ai_post(json.loads(data.decode('utf-8')), quality=False, timeout=30)
        picks = _ai_parse_json(r['choices'][0]['message']['content'])
        if not picks:
            raise ValueError('未返回可解析 JSON')
        write_json(os.path.join(DATA_DIR, 'ai_stock_picks.json'), picks)
        print(f'[AI] Stock picks: {len(picks.get("picks",[]))} candidates')
    except Exception as e:
        print(f'[AI] Stock picks failed: {e}')

def generate_ai_market_insight():
    """AI 全量市场洞察 — 一次调用，聚合摘要分析全量饰品"""
    if not _ai_provider_ready(quality=True): return
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
        r = _ai_post(json.loads(data.decode('utf-8')), quality=True, timeout=30)
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
    if not _ai_provider_ready(quality=False): return
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
        r = _ai_post(json.loads(data.decode('utf-8')), quality=False, timeout=30)
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
    except Exception as _e:
        print(f'[WARN] 读取 AI 历史教训失败: {_e}', file=sys.stderr)
        return ''

def _get_scoring_weights_from_lessons():
    """从追踪教训中提取评分权重调整（反哺推荐引擎）
    返回 (eco_multiplier, buff_multiplier)，默认 (1.0, 1.0)
    """
    try:
        import json, os
        # ⚠ 2026-09-18：lessons 权重（eco×0.8/buff×1.2）由 AI 叙述生成、**无实测依据**
        #   （记分卡显示"稀缺"类信号实测为负贡献）→ 默认中性；dims 样本够了再按实测标定。
        #   启用：REC_USE_LESSON_WEIGHTS=1
        if str(os.environ.get('REC_USE_LESSON_WEIGHTS', '0')).strip() != '1':
            return 1.0, 1.0
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
            except Exception as _e:
                print(f'[WARN] 解析权重反馈系数失败: {_e}', file=sys.stderr)
            return 1.0
        
        eco_m = parse_pct(eco_advice)
        buff_m = parse_pct(buff_advice)
        if eco_m != 1.0 or buff_m != 1.0:
            print(f'[REC] AI反馈: ECO×{eco_m:.2f} BUFF×{buff_m:.2f} (from tracking lessons)')
        return eco_m, buff_m
    except Exception as _e:
        print(f'[WARN] 计算推荐权重失败: {_e}', file=sys.stderr)
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
    except Exception as _e:
        print(f'[WARN] 构造推荐理由(旧路径)失败: {_e}', file=sys.stderr)
        return None

# ═══════════════ AI 推荐（v7：只用真实可用盘口 + 原型选品 + 逐件独立生成）2026-09-17 ═══════════════
# 排查发现推荐池数据退化：30 条 score 全为 48.0、tag_label 全同一句、
#   n_steam/n_dev_steam/n_premium_buff/n_premium_yyyp/n_ref_src 全为空、BUFF/悠悠 在售与求购均为 0，
#   而 _reason 里的「BUFF溢价53%」是相对 ECO（低位档）算的假指标。
#   → 每件的输入几乎一样，模型无料可差异化，只能换数字（这就是"文案都一样"的根因）。
# 真实可用字段：price(=eco_price)、eco_selling(在售)、eco_qg_total(求购单)、eco_qg_price(求购价)、
#   eco_history(走势)、n_cov。因此 v7 的原型改为这三个可算的盘口结构：
#   ① 供给稀缺(在售少) ② 买盘坚挺(求购价贴近/高于售价) ③ 求购活跃(求购单占比高)
#   并彻底剔除 ECO 溢价类假指标。

_REC_BANNED = ['价格波动', '投资需谨慎', '值得关注', '市场情绪', '合理区间', '波动风险', '潜力巨大', '市场波动', '溢价强劲']
_REC_ARCH_ORDER = ['供给稀缺', '买盘承接', '求购活跃']


def _rec_f(v, d=0.0):
    try:
        f = float(v)
        if f != f or f in (float('inf'), float('-inf')):
            return d
        return f
    except Exception:
        return d


def _fmt_pct(v):
    try:
        f = float(v)
    except Exception:
        return '—'
    if f != f:
        return '—'
    return '%+.1f%%' % f


def _rec_book(item):
    """真实盘口（ECO 口径；BUFF/悠悠 无挂单数据时不可用）"""
    price = _rec_f(item.get('price'))
    sell = _rec_f(item.get('eco_selling'))
    qg = _rec_f(item.get('eco_qg_total'))
    qgp = _rec_f(item.get('eco_qg_price'))
    cushion = ((qgp / price - 1) * 100.0) if (qgp > 0 and price > 0) else None
    tight = (qg / (sell + qg)) if (sell + qg) > 0 else 0.0
    return dict(price=price, sell=sell, qg=qg, qgp=qgp, cushion=cushion, tight=tight)


def _rec_levels(item):
    """确定性价位/仓位（由该件自身数据推导）"""
    price = _rec_f(item.get('price'))
    bk = _rec_book(item)
    hist = [x for x in (item.get('eco_history') or []) if _rec_f(x) > 0]
    if len(hist) < 3:
        hist = [x for x in (item.get('multi_history') or []) if _rec_f(x) > 0]
    vol = 0.0
    if len(hist) >= 4:
        mu = sum(hist) / len(hist)
        if mu > 0:
            var = sum((x - mu) ** 2 for x in hist) / len(hist)
            vol = (var ** 0.5) / mu * 100.0
    # 入场下沿：求购价上浮2%（有买盘托底）；否则现价-3%
    zl = (bk['qgp'] * 1.02) if bk['qgp'] > 0 else (price * 0.97)
    zh = price * 0.99
    if price > 0 and zl >= zh:
        zl, zh = price * 0.95, price * 0.99
    tp = min(25.0, max(8.0, round(vol * 1.6, 1)))
    sl = min(15.0, max(5.0, round(vol * 0.9, 1)))
    # 仓位：买盘越弱/单价越高，仓位越小
    if price >= 3000 or bk['tight'] < 0.05:
        pos = 5
    elif bk['tight'] >= 0.25:
        pos = 15
    else:
        pos = 10
    return dict(price=price, vol=round(vol, 1), zl=round(zl), zh=round(zh), tp=tp, sl=sl, pos=pos,
                tight=round(bk['tight'], 3), cushion=bk['cushion'], sell=bk['sell'], qg=bk['qg'], qgp=bk['qgp'])


def _rec_signals(item, lv):
    """该件独有的关键信号（只用 ECO 真实盘口 + 走势，不含假指标）"""
    sigs = []
    sell, qg = lv['sell'], lv['qg']
    if sell > 0 and qg > 0:
        sigs.append(('+' if lv['tight'] >= 0.15 else '=') + '买卖盘%d求购/%d在售' % (qg, sell))
    elif sell > 0:
        sigs.append('-仅%d在售·无求购挂单' % sell)
    elif qg > 0:
        sigs.append('+%d求购·无在售' % qg)
    if lv['cushion'] is not None:
        c = lv['cushion']
        sigs.append(('+' if c >= -6 else ('-' if c <= -15 else '=')) + '求购价距售价%+.1f%%' % c)
    if sell and sell <= 20:
        sigs.append('+在售稀少·%d件' % sell)
    elif sell >= 60:
        sigs.append('-在售偏多·%d件' % sell)
    if lv['vol'] >= 6:
        sigs.append('-波动大σ%.1f%%' % lv['vol'])
    elif 0 < lv['vol'] <= 2.5:
        sigs.append('=波动温和σ%.1f%%' % lv['vol'])
    r7 = _rec_f(item.get('rate_7'))
    r30 = _rec_f(item.get('rate_30'))
    if r7 > 0 and r30 > 0:
        sigs.append('+7日/30日双升')
    elif r7 < 0 and r30 < 0:
        sigs.append('-7日/30日双降')
    dev = item.get('n_dev_steam')
    if isinstance(dev, (int, float)) and abs(dev) > 25:
        sigs.append(('+' if dev > 0 else '-') + '国内相对Steam偏离%+.0f%%' % dev)
    seen, out = set(), []
    for s in sigs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:4]


def _rec_diff_score(picks):
    """两两 2-gram 最大重合率（越小越好）"""
    def grams(s):
        s = ''.join(ch for ch in s if ch.strip())
        return set(s[i:i + 2] for i in range(len(s) - 1))
    gs = [grams(str((p.get('reason') or '') + (p.get('risk') or '') + (p.get('operation') or ''))) for p in picks]
    worst = 0.0
    for i in range(len(gs)):
        for j in range(i + 1, len(gs)):
            a, b = gs[i], gs[j]
            if not a or not b:
                continue
            worst = max(worst, len(a & b) / len(a | b))
    return round(worst, 3)


def _rec_select_slots(cands):
    """三个原型各选 1 件（全部基于 ECO 真实盘口，结构上保证三条不同）"""
    if not cands:
        return []
    lvs = [_rec_levels(it) for it in cands]
    dims = {
        _REC_ARCH_ORDER[0]: [-(lv['sell'] or 9999) for lv in lvs],           # 在售越少越好
        _REC_ARCH_ORDER[1]: [-(lv['cushion'] if lv['cushion'] is not None else -99) for lv in lvs],  # 求购价越贴近售价越好
        _REC_ARCH_ORDER[2]: [lv['tight'] for lv in lvs],                     # 求购单占比越高越好
    }
    chosen, used = [], set()
    for arch in _REC_ARCH_ORDER:
        arr = dims[arch]
        basis = [i for i in range(len(cands)) if i not in used]
        if not basis:
            break
        best_i = max(basis, key=lambda i: arr[i])
        used.add(best_i)
        it = cands[best_i]
        lv = lvs[best_i]
        chosen.append((arch, it, lv, _rec_signals(it, lv)))
    return chosen


def _rec_item_block(item, lv, sigs):
    """单件数据块（只用真实可用口径）"""
    bk = _rec_book(item)
    steam = _rec_f(item.get('n_steam')) or _rec_f(item.get('steam_sell'))
    b = _rec_f(item.get('buff_sell'))
    bn = _rec_f(item.get('buff_sell_num'))
    y = _rec_f(item.get('yyyp_sell'))
    yn = _rec_f(item.get('yyyp_sell_num'))
    dev = item.get('n_dev_steam')
    dev_txt = ('%+.0f%%' % dev) if isinstance(dev, (int, float)) else '无数据（本件不可谈跨市场）'
    return (
        '名称: %s\n品类: %s | 评级: %s | 综合评分: %.1f\n'
        'ECO 盘口（唯一有效盘口）: 售价 ¥%.2f · 在售 %d 件 · 求购 %d 单 @ ¥%.2f → 求购价距售价 %s，求购单占比 %.0f%%\n'
        'BUFF 快照: %s | 悠悠 快照: %s\n'
        'Steam 独立市场: %s · Steam 偏离度: %s（基准=常态比 1.45）\n'
        '走势: 1日%s 7日%s 30日%s 月%s | 历史波动σ=%.1f%%\n'
        '引擎算好的参考价位: 入场 ¥%d–¥%d · 止盈 +%.1f%% · 止损 -%.1f%% · 建议仓位 %d%%\n'
        '该件可用信号: %s\n引擎原判(已清洗假溢价): %s\n'
        '⚠ 注意：BUFF/悠悠 无挂单数据时，其快照价不可用于判断买卖渠道；ECO 是低价档参考盘，禁止用它算"溢价率"。'
        % (item.get('name', '?'),
           item.get('fp_category') or item.get('_cat') or '—',
           item.get('fp_rarity') or '—',
           _rec_f(item.get('score')),
           bk['price'], int(bk['sell']), int(bk['qg']), bk['qgp'],
           (('%+.1f%%' % bk['cushion']) + '（负值越大＝买盘出价越低、承接越弱；-8% 以内才算强承接）') if bk['cushion'] is not None else '无求购价',
           bk['tight'] * 100,
           ('¥%.2f（在售%d件）' % (b, int(bn))) if b > 0 else '无数据',
           ('¥%.2f（在售%d件）' % (y, int(yn))) if y > 0 else '无数据',
           ('¥%.2f' % steam) if steam > 0 else '无数据',
           dev_txt,
           _fmt_pct(item.get('rate_1')), _fmt_pct(item.get('rate_7')),
           _fmt_pct(item.get('rate_30')), _fmt_pct(item.get('fp_month_ratio')), lv['vol'],
           lv['zl'], lv['zh'], lv['tp'], lv['sl'], lv['pos'],
           ' '.join(sigs), _rec_clean_reason(item.get('_reason'))[:70])
    )


def _rec_market_context(all_items):
    parts = []
    for fn, key, label in (('ai_news_impact.json', 'impact', '市场新闻'),
                           ('ai_market_insight.json', 'insight', '市场洞察')):
        try:
            d = read_json(os.path.join(DATA_DIR, fn))
            if d and d.get(key):
                parts.append('%s: %s' % (label, str(d[key])[:150]))
        except Exception:
            pass
    try:
        scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
        if scan:
            parts.append('全市场: %s件·均价¥%.0f·追踪%s件' % (
                scan.get('total', '?'), _rec_f(scan.get('avg_p')), scan.get('tracked', '?')))
            movers = scan.get('movers', {}) or {}
            g = (movers.get('gainers') or [])[:3]
            l = (movers.get('losers') or [])[:3]
            if g:
                parts.append('领涨: ' + ', '.join((x.get('n', '?')[:12] + '%+d%%' % _rec_f(x.get('r7'))) for x in g))
            if l:
                parts.append('领跌: ' + ', '.join((x.get('n', '?')[:12] + '%+d%%' % _rec_f(x.get('r7'))) for x in l))
    except Exception:
        pass
    prices = [_rec_f(it.get('price')) for it in all_items[:50] if _rec_f(it.get('price')) > 0]
    if prices:
        parts.append('候选价格区间: ¥%.0f~¥%.0f·中位¥%.0f' % (
            min(prices), max(prices), sorted(prices)[len(prices) // 2]))
    return ('\n'.join(parts) + '\n') if parts else '（无外部市场信息，仅依据候选池数据判断）\n'


def _rec_chat(prompt, model, system=None, temperature=0.85, timeout=120, max_tokens=2000):
    msgs = []
    if system:
        msgs.append({'role': 'system', 'content': system})
    msgs.append({'role': 'user', 'content': prompt})
    txt = _ai_call(msgs, max_tokens=max_tokens, temperature=temperature,
                   json_mode=True, quality=True, timeout=timeout, model=model)
    if txt is None:
        raise RuntimeError('推荐 AI 调用失败（provider=%s）' % _ai_provider(True))
    return txt


def _rec_safe_parse(raw, want_key='picks'):
    import re
    try:
        o = json.loads(raw)
        if o.get(want_key) is not None:
            return o
    except Exception:
        pass
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if m:
        try:
            o = json.loads(m.group(1))
            if o.get(want_key) is not None:
                return o
        except Exception:
            pass
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None


def _rec_fuzzy_price(name, cands):
    def norm(s):
        s = str(s or '')
        for ch in '（）()|｜·、,， ':
            s = s.replace(ch, '')
        return s.lower()
    n = norm(name)
    if not n:
        return None
    best, best_len = None, -1
    for c in cands:
        cn = norm(c.get('name'))
        if not cn:
            continue
        if cn == n or cn.startswith(n) or n.startswith(cn):
            if len(cn) > best_len:
                best, best_len = c, len(cn)
    return round(_rec_f(best.get('price'))) if best is not None else None


def _rec_clean_reason(txt):
    """清洗引擎原判里的假指标（ECO 口径溢价）与自检噪声"""
    import re as _re
    txt = _re.sub(r'(?:BUFF|悠悠|ECO)?\s*溢价\s*[+-]?\d+(?:\.\d+)?%', '', str(txt or ''))
    txt = _re.sub(r'\[AI建议\][^|]*', '', txt)
    txt = _re.sub(r'[|｜]\s*(?=[|｜])', '', txt)
    return txt.strip(' |｜')


def _rec_fix_platform(item, lv):
    """平台建议由数据确定性生成（模型容易把方向写反；无挂单时不可建议套利）"""
    b = _rec_f(item.get('buff_sell'))
    bn = _rec_f(item.get('buff_sell_num'))
    y = _rec_f(item.get('yyyp_sell'))
    yn = _rec_f(item.get('yyyp_sell_num'))
    if bn > 0 and yn > 0:
        if b < y:
            return '买入走 BUFF（¥%.0f，比悠悠低 ¥%.0f）· 卖出/挂单走 悠悠（¥%.0f）' % (b, y - b, y)
        return '买入走 悠悠（¥%.0f，比BUFF低 ¥%.0f）· 卖出/挂单走 BUFF（¥%.0f）' % (y, b - y, b)
    if bn > 0 or yn > 0:
        who, p = ('BUFF', b) if bn > 0 else ('悠悠', y)
        return '仅 %s 有在售挂单（¥%.0f），另一平台无挂单，暂不具备跨平台套利条件' % (who, p)
    # 两平台都无挂单 → 只能基于 ECO 盘口（在售/求购）给建议
    if lv['qgp'] > 0 and lv['sell'] > 0:
        return 'BUFF/悠悠 均无在售挂单（快照价不可用）；按 ECO 盘口操作：靠近求购价 ¥%.0f 挂单接货，参考在售 %d 件择机出货' % (
            lv['qgp'], int(lv['sell']))
    return '各平台均无在售挂单数据，暂不具备下单条件；等盘口恢复再评估'


_REC_ANGLE = {
    '供给稀缺': '围绕「ECO 在售挂单稀少、可流通货源紧」来论证，用「在售 N 件」这个数字说话。',
    '买盘承接': '围绕「求购价与售价的差距」来论证：差距越小，说明买盘越愿意按现价接货，承接越强；差距大则说明买盘出价低、承接弱。',
    '求购活跃': '围绕「求购单数在盘口中的占比高、需求端活跃」来论证，用「N 求购 / M 在售」这个比例说话。',
}


_REC_SENTIMENTS = ['强烈看多', '看多', '中性偏多', '中性', '中性偏空', '看空', '强烈看空']


def _rec_sentiment_from_data(item, lv):
    """模型 sentiment 不合法时的兜底：按 Steam 偏离 / 买盘承接 / 7日趋势 三票打分"""
    dev = item.get('n_dev_steam')
    tight = lv.get('tight', 0) or 0
    r7 = _rec_f(item.get('rate_7'))
    pts = 0
    if isinstance(dev, (int, float)):
        pts += 1 if dev > 25 else (-1 if dev < -25 else 0)
    pts += 1 if tight >= 0.20 else (-1 if tight < 0.05 else 0)
    pts += 1 if r7 > 0 else (-1 if r7 < 0 else 0)
    if pts >= 2:
        return '看多'
    if pts == 1:
        return '中性偏多'
    if pts == 0:
        return '中性'
    if pts == -1:
        return '中性偏空'
    return '看空'


def _rec_fix_sentiment(one, item, lv):
    """把 sentiment 归一到 7 个合法档位（实测本地 7B 会往里写策略整句）"""
    raw = str(one.get('sentiment') or '').strip()
    for s in _REC_SENTIMENTS:
        if s in raw:
            return s
    fixed = _rec_sentiment_from_data(item, lv)
    if raw:
        print('[AI] sentiment %r 不合法 → 归一为 %s' % (raw[:20], fixed))
    return fixed


def _rec_text_of(p):
    """取一条 pick 的全部正文（用于质量检查）"""
    return ''.join(str(p.get(k) or '') for k in
                   ('reason', 'risk', 'operation', 'price_zone', 'platform_advice'))


# 合法英文白名单（平台名 / 常见枪械与系列代号）——只用于「中英夹杂」检测，避免误报
_REC_EN_OK = ('BUFF', 'STEAM', 'ECO', 'STATTRAK', 'T+7', 'AI', 'MW', 'FN', 'FT', 'WW', 'BS')


def _rec_english_hits(txt):
    """检测非白名单的英文单词（本地小模型容易出现「这件 Buff 类品」这类夹杂）"""
    import re as _re
    bad = []
    for w in _re.findall(r'[A-Za-z][A-Za-z\-]{1,}', txt or ''):
        u = w.upper().replace('-', '')
        if any(u.startswith(k.replace('-', '')) for k in _REC_EN_OK):
            continue
        if w in bad:
            continue
        bad.append(w)
    return bad


def _rec_cloud_review(plist, market_ctx):
    """质量协同（#6）：把本地生成的 3 条交给云端做一次「审校+改写」。

    现实取舍：本地 7B 结构稳（字段/sentiment/重合率由代码保证），但文案常有空话词、
    中英夹杂与自相矛盾。这里用**一次**云端调用统一审校（只有 1 次，成本可忽略）。
    返回改写后的 picks（不可用时返回 None，调用方保留本地版本）。
    关闭：环境变量 AI_REC_REVIEW_CLOUD=0
    """
    if str(os.environ.get('AI_REC_REVIEW_CLOUD', '1')).strip() == '0':
        return None
    if not ZHIPU_KEY:
        return None
    if not plist:
        return None
    banned = '、'.join(_REC_BANNED)

    def _brief(p):
        return ('【%s】角度:%s\n  理由: %s\n  风险: %s\n  操作: %s\n  区间: %s\n  平台: %s'
                % (p.get('name'), p.get('archetype'), p.get('reason'), p.get('risk'),
                   p.get('operation'), p.get('price_zone'), p.get('platform_advice')))

    prompt = (
        '你是资深中文财经编辑，负责**审校**下面 3 条 CS2 饰品买入分析（由本地小模型起草）。\n\n'
        '【待审校内容】\n' + '\n\n'.join(_brief(p) for p in plist) + '\n\n'
        '【市场背景】\n' + (market_ctx or '') + '\n'
        '【审校要求】\n'
        '1. 禁用这些空话词：' + banned + '。命中就改写成本文数据支撑的具体表述。\n'
        '2. 清除中英夹杂：除平台名 BUFF/悠悠/Steam/ECO 与饰品本身的英文型号外，正文用中文。\n'
        '3. 修掉自相矛盾或逻辑不通的句子（例：「在售件数较多，只有16件」）。\n'
        '4. 保持原意与原有的数字（不得编造新数字、不得改动入场区间/止盈/止损/仓位）。\n'
        '5. 三条之间继续保证措辞不雷同；每段长度与原段相当（理由 100-150 字 / 风险 80-120 字 / 操作 80-120 字）。\n'
        '6. 只输出 JSON：{"picks":[{"name":"与输入完全一致","reason":"","risk":"","operation":"",'
        '"price_zone":"","platform_advice":""}]}（不要输出其他字段）'
    )
    try:
        txt = _ai_call([{'role': 'system', 'content': '你是中文财经编辑，只输出 JSON。'},
                        {'role': 'user', 'content': prompt}],
                       max_tokens=2600, temperature=0.3, json_mode=True,
                       quality=True, timeout=120, provider='zhipu')
        got = _ai_parse_json(txt)
        if not got or not got.get('picks'):
            print('[AI] 云端审校未返回可用 JSON，保留本地版本')
            return None
        by_name = {}
        for p in got['picks']:
            if p.get('name'):
                by_name[str(p['name'])] = p
        merged = 0
        for p in plist:
            src = by_name.get(str(p.get('name')))
            if not src:
                continue
            for k in ('reason', 'risk', 'operation', 'price_zone', 'platform_advice'):
                v = str(src.get(k) or '').strip()
                if v and v != str(p.get(k) or ''):
                    p[k] = v
                    merged += 1
        print('[AI] 云端审校完成（改写 %d 处文本），model=%s' % (merged, ZHIPU_MODEL))
        return plist
    except Exception as e:
        print('[AI] 云端审校失败（保留本地版本）: %s' % str(e)[:120], file=sys.stderr)
        return None


def _rec_write_one(item, lv, sigs, archetype, model, market_ctx, others, extra=''):
    """单件独立调用：只喂这一件 → 机制上杜绝三条套同一模板
    小模型（本地 7B）更服从**末尾**指令，因此把禁令与自检清单放在 prompt 最后。"""
    banned = '、'.join(_REC_BANNED)
    prompt = (
        '你是 CS2 饰品投资分析师。请只分析下面这 1 件标的，写出它自己的买入分析。\n\n'
        '【这件标的数据】\n' + _rec_item_block(item, lv, sigs) + '\n\n'
        '【本次指定的分析角度】' + archetype + '——' + _REC_ANGLE.get(archetype, '围绕该件最突出的数据特征来论证。') + '\n\n'
        '【市场背景】\n' + market_ctx + '\n'
        + (('【本次已写的其他标的（措辞与结论都不得与它们重复）】\n' + others + '\n') if others else '')
        + (extra + '\n' if extra else '')
        + '\n【写作要求】\n'
        '- reason 100-150字：核心逻辑 + 供需(引用在售/求购) + 溢价结构 + 流动性/变现(T+7锁定期最少7天)。\n'
        '- risk 80-120字：只讲这件最致命的 2 个风险，各带数据。\n'
        '- operation 80-120字：必须引用「引擎算好的参考价位」的入场区间/止盈/止损/仓位，'
        '给出加仓与退出条件，持有周期 ≥7 天。\n'
        '- price_zone 30-50字；platform_advice 20-40字；sentiment 1-2词；trend_signals 3-4项。\n'
        '- 必须引用数据里的具体数字（在售件数/求购单数/求购价距售价/Steam偏离/波动σ/入场区间）至少 3 处。\n'
        '- 严禁用 ECO 售价去算任何"溢价率"；BUFF/悠悠 无挂单时不得用其快照价判断渠道。\n'
        '- 语气像实战顾问，句子自然，不要罗列标签词。\n\n'
        '【输出 JSON，仅这 7 个字段】\n'
        '{"reason":"","risk":"","operation":"","price_zone":"","sentiment":"","trend_signals":["","",""],"platform_advice":""}\n\n'
        '【最后自检——违反则重写（尤其重要）】\n'
        '1. 全文禁止出现这些空话词：' + banned + '。\n'
        '2. 禁止出现英文单词与夹杂词（平台名 BUFF / 悠悠 / Steam / ECO 除外）。'
        '若想写"件数"就写"件"或"挂单"，不要写 piece / Engin / Buff 之类。\n'
        '3. 每个字段都要写满规定字数，不要只写一句话就结束。\n'
        '4. 只输出一个 JSON 对象，不要任何解释、不要 markdown 围栏。'
    )
    return _rec_safe_parse(_rec_chat(
        prompt, model,
        '你是CS2饰品投资分析师。只返回JSON。严格基于输入数据，禁止编造数字，禁止套用固定句式。'
        '禁止使用"价格波动""市场情绪""市场波动"这类空话词，禁止中英夹杂。', 0.85),
        want_key='reason')


def generate_ai_recommendations():
    """AI 购买推荐分析 v7 — 真实盘口驱动 + 原型选品 + 逐件独立生成"""
    if not ZHIPU_KEY:
        return
    try:
        market = read_json(os.path.join(DATA_DIR, 'market.json'))
        all_items = (market.get('recommendations', {}) or {}).get('all', [])
        if not all_items:
            print('[AI] No recommendations to analyze')
            return
        cands = all_items[:12]
        model = os.environ.get('AI_REC_MODEL') or None   # 空则按 provider 选默认模型
        market_ctx = _rec_market_context(all_items)

        slots = _rec_select_slots(cands)
        if not slots:
            print('[AI] No slots selected')
            return
        print('[AI] 原型选品: ' + ' | '.join('%s→%s' % (a, it.get('name', '?')) for a, it, _, _ in slots))

        plist, others_txt = [], ''
        for idx, (arch, item, lv, sigs) in enumerate(slots):
            one = None
            try:
                one = _rec_write_one(item, lv, sigs, arch, model, market_ctx, others_txt)
            except Exception as _e:
                print('[AI] 第%d件生成失败: %s' % (idx + 1, _e))
            if not one or not one.get('reason'):
                one = {
                    'reason': '引擎按「%s」原型选出该件：售价 ¥%.0f，在售 %d 件，求购 %d 单 @ ¥%.0f，'
                              '求购价距售价 %s；入场参考 ¥%d–¥%d。'
                              % (arch, lv['price'], int(lv['sell']), int(lv['qg']), lv['qgp'],
                                 ('%+.1f%%' % lv['cushion']) if lv['cushion'] is not None else '未知',
                                 lv['zl'], lv['zh']),
                    'risk': '规则化推荐缺少模型二次校验，须按纪律执行止损 -%.1f%%。' % lv['sl'],
                    'operation': '入场 ¥%d–¥%d 分批建仓，止盈 +%.1f%%，止损 -%.1f%%，仓位 %d%%，持有 ≥7 天。'
                                 % (lv['zl'], lv['zh'], lv['tp'], lv['sl'], lv['pos']),
                    'price_zone': '参考区间 ¥%d–¥%d（引擎计算）' % (lv['zl'], lv['zh']),
                    'sentiment': _rec_sentiment_from_data(item, lv), 'trend_signals': sigs,
                    'platform_advice': _rec_fix_platform(item, lv)
                }
            # 质量门：空话词（禁用清单）+ 中英夹杂（白名单外英文单词）
            blob = _rec_text_of(one)
            hits = [w for w in _REC_BANNED if w in blob]
            en_hits = _rec_english_hits(blob)
            _need_fix = (len(hits) >= 2) or (bool(hits) and bool(en_hits))
            if _need_fix:
                try:
                    _why = []
                    if hits:
                        _why.append('被禁用的空话词（' + '、'.join(hits) + '）')
                    if en_hits:
                        _why.append('中英夹杂（' + '、'.join(en_hits[:5]) + '）')
                    fix = _rec_write_one(item, lv, sigs, arch, model, market_ctx, others_txt,
                                         extra='注意：上一次输出出现了 ' + ' 与 '.join(_why) + '，本次务必改写成纯中文、带具体数据的表述。')
                    if fix and fix.get('reason'):
                        one = fix
                        print('[AI] 第%d件命中 %s → 已重写' % (idx + 1, ' / '.join(_why)))
                except Exception as _e:
                    print('[AI] 第%d件重写失败: %s' % (idx + 1, _e))
            one['rank'] = idx + 1
            one['name'] = item.get('name', '')
            one['archetype'] = arch
            one['sentiment'] = _rec_fix_sentiment(one, item, lv)
            _fixed = _rec_fix_platform(item, lv)
            if str(one.get('platform_advice') or '').strip() != _fixed:
                one['platform_advice'] = _fixed
            # 信号一律用引擎按真实数据算出的（模型给的常混入旧假溢价与引擎原判原文）
            import re as _re2
            _extra = []
            if isinstance(one.get('trend_signals'), list):
                for _s in one['trend_signals']:
                    _s = str(_s).strip()
                    if not _s or len(_s) > 24:
                        continue
                    if any(_bad in _s for _bad in ('ECO', 'vs', '综合', '溢价强劲', 'AI优选', '|')):
                        continue
                    if _re2.match(r'^[+\-\=]', _s) and _s not in sigs:
                        _extra.append(_s)
            one['trend_signals'] = (sigs + _extra)[:4]
            pr = one.get('price') or _rec_fuzzy_price(one['name'], cands)
            if pr:
                one['price'] = pr
            plist.append(one)
            others_txt += '- %s（角度:%s）风险要点: %s\n' % (one['name'], arch, str(one.get('risk', ''))[:60])

        # ── 质量协同（#6）：本地起草 → 云端审校一次（可 AI_REC_REVIEW_CLOUD=0 关闭）──
        try:
            _before = sum(1 for p in plist for w in _REC_BANNED if w in _rec_text_of(p))
            _before_en = sum(len(_rec_english_hits(_rec_text_of(p))) for p in plist)
            _rev = _rec_cloud_review(plist, market_ctx)
            if _rev is not None:
                _after = sum(1 for p in plist for w in _REC_BANNED if w in _rec_text_of(p))
                _after_en = sum(len(_rec_english_hits(_rec_text_of(p))) for p in plist)
                print('[AI] 审校前后：空话词 %d→%d，中英夹杂 %d→%d' % (_before, _after, _before_en, _after_en))
            else:
                print('[AI] 跳过云端审校（本地版本保留）；空话词 %d / 中英夹杂 %d' % (_before, _before_en))
        except Exception as _re2:
            print('[AI] 云端审校异常（保留本地版本）: %s' % str(_re2)[:120], file=sys.stderr)

        head = {'reasoning': '', 'strategy': '', 'summary': '', 'self_critique': ''}
        try:
            hp_body = ('下面是你刚为今日选出的 %d 件标的（角度: %s）：\n%s\n\n市场背景：\n%s\n'
                       '请输出整体结论 JSON：{"reasoning":"120-160字：市场判断 + 为什么是这3件 + 为什么不是第4名",'
                       '"strategy":"50-80字整体策略","summary":"50-80字总结","self_critique":"50字：本次判断最可能错在哪"}\n'
                       '禁止出现这些空话词：' + '、'.join(_REC_BANNED))
            hp = hp_body % (len(plist), '/'.join(p.get('archetype', '') for p in plist),
                            '\n'.join('- %s(%s): %s' % (p['name'], p.get('archetype', ''), str(p.get('reason', ''))[:60]) for p in plist),
                            market_ctx)
            got = _rec_safe_parse(_rec_chat(hp, model, '你是CS2饰品投资分析师。只返回JSON对象。', 0.7, 90, 1200),
                                  want_key='reasoning') or {}
            for k in head:
                if got.get(k):
                    head[k] = str(got[k])
        except Exception as _e:
            print('[AI] 整体结论生成失败（用兜底）: %s' % _e)
        if not head['strategy']:
            head['strategy'] = '按「%s」三条主线分散配置，单件仓位不超过 15%%，锁定 7 天后按止盈止损执行。' % (
                '/'.join(p.get('archetype', '') for p in plist))
        if not head['summary']:
            head['summary'] = '本次从 %d 件候选中按供给稀缺/买盘坚挺/求购活跃三条盘口主线各选 1 件。' % len(cands)
        if not head['self_critique']:
            head['self_critique'] = '本池 BUFF/悠悠 盘口与 Steam 数据缺失，判断只基于 ECO 单一盘口，结论鲁棒性有限。'

        out = {'picks': plist, 'date': time.strftime('%Y-%m-%d %H:%M'), 'total_candidates': len(cands)}
        out.update(head)
        ds = _rec_diff_score(plist) if len(plist) > 1 else None
        if ds is not None:
            banned_hits = sum(1 for p in plist for w in _REC_BANNED if w in _rec_text_of(p))
            en_hits_total = sum(len(_rec_english_hits(_rec_text_of(p))) for p in plist)
            out['quality'] = {'max_pairwise_overlap': ds, 'template_risk': ds > 0.45,
                              'model': _ai_model_name(True, model), 'picks': len(plist), 'banned_hits': banned_hits,
                              'en_hits': en_hits_total,
                              'reviewed_by_cloud': str(os.environ.get('AI_REC_REVIEW_CLOUD', '1')).strip() != '0'}
            print('[AI] 差异化校验：最大两两重合率 %.2f%s，空话词残留 %d' % (ds, '（偏高）' if ds > 0.45 else '（通过）', banned_hits))
        try:
            eco_m, buff_m = _get_scoring_weights_from_lessons()
            if eco_m != 1.0 or buff_m != 1.0:
                out['scoring_weights'] = {'eco': round((eco_m - 1) * 100), 'buff': round((buff_m - 1) * 100)}
        except Exception as _e:
            print('[WARN] 写 AI 推荐前处理失败: %s' % _e, file=sys.stderr)
        write_json(os.path.join(DATA_DIR, 'ai_recommendations.json'), out)
        print('[AI] Recommendations: %d picks generated (v7)' % len(plist))
    except Exception as e:
        print('[AI] Recommendations failed: %s' % e)

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
        last_err = None
        for attempt in range(3):
            try:
                git_push_locally(sorted(dirty_files), message)
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f'[PUSH] Attempt {attempt+1} failed: {e}', file=sys.stderr)
                if attempt < 2:
                    time.sleep(3)
                    # ⚠️ 重试**不再** fetch + rebase。
                    #   实测（2026-09-16）这条仓库里 fetch 从没真正下到对象
                    #   （FETCH_HEAD 写了、对象没下来），而 rebase 一旦被超时
                    #   强杀就会清空 refs/ → 仓库变 "not a git repository"。
                    #   更关键的是：远端数据比本地旧，rebase 进来只会覆盖新数据。
                    #   所以重试只做纯 push —— push 不需要远端对象在本地存在。
                    pass
        if last_err is not None:
            # 必须让调用方知道数据没推上去 —— 否则自动任务会「静默成功」地空转。
            raise RuntimeError(f'push 重试 3 次全部失败，数据未推送: {last_err}')

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
    except Exception as _e:
        print(f'[WARN] 读取远端 SHA 失败: {_e}', file=sys.stderr)

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

def _git_auth_args():
    """构造带鉴权的 git 参数（优先 token）。

    ⚠️ 这里是踩过大坑的地方（2026-09-16）：**GitHub 的 git smart HTTP
    不接受 `Authorization: Bearer <token>`** —— 那是 GitHub *API* 的格式。
    用 Bearer 时 git 服务端视作未认证，于是退回向用户索要密码，
    在非交互环境直接报：

        fatal: Cannot prompt because user interactivity has been disabled.
        fatal: unable to get password from user

    正确格式是 HTTP **Basic**：`x-access-token:<token>`。
    实测对照（`git ls-remote`）：
        Bearer  → rc=128 失败
        Basic   → rc=0   成功
    用 `http.extraHeader` 传（而不是把 token 写进 remote URL），
    好处是不会在 `.git/config` 里留下明文。
    """
    if GH_TOKEN:
        b64 = base64.b64encode(
            ('x-access-token:' + GH_TOKEN).encode('utf-8')).decode('ascii')
        return ['-c', 'http.extraHeader=Authorization: Basic ' + b64,
                '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=false']
    return list(GIT_BASE)


def git_push_locally(files, message):
    """Push via local git in a single commit (token-based auth, no popup)

    失败时**抛异常**。原实现只把错误打到 stderr 就返回，于是上游
    `for attempt in range(3)` 的重试循环永远拿不到异常、一次都不会重试，
    而且 update.py 最终仍以 rc=0 退出 —— 表面「成功」，实际数据没推上去
    （2026-09-15 就是这么连续空转了 2.9 小时）。
    """
    git_env = GIT_ENV
    cf = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

    # 逐文件 -f 强加：这批数据文件多被 .gitignore 排除（如 *.db / *.log），
    # 必须 -f 才会进暂存区。
    for f in files:
        rc, _, err = _git_run(['add', '-f', f], timeout=120)
        if rc != 0:
            raise RuntimeError(f'git add -f {f} 失败 rc={rc}: {err.strip()[:160]}')

    # ⚠️ 提交前先确认暂存区**真的有**改动。
    #   `git commit` 在"没有东西可提交"时返回 rc=1，且 stdout/stderr 都可能为空
    #   （取决于 git 版本与 --no-verify），靠匹配 'nothing to commit' 不可靠 ——
    #   实测就是这样误报 `git commit 失败 rc=1: ` 的。
    rc, staged, err = _git_run(['diff', '--cached', '--name-only'], timeout=120)
    if rc != 0:
        raise RuntimeError(f'git diff --cached 失败 rc={rc}: {err.strip()[:160]}')
    if not staged.strip():
        print('[PUSH] 暂存区无改动，跳过 commit（数据与 HEAD 一致）')
    else:
        rc, out, err = _git_run(['commit', '-m', message, '--no-verify'], timeout=180)
        if rc != 0:
            raise RuntimeError(f'git commit 失败 rc={rc}: {(err or out).strip()[:250]}')

    # Push: 优先 Token（HTTP Basic，见 _git_auth_args），fallback 到空 credential helper
    # （push 超时**不强杀**：push 中断可能留下半推的 ref 状态，代价高于多等一会儿）
    #
    # ⚠️ 关于 `--force-with-lease`：本仓库是 shallow clone，本地 main 与远端
    #    main **没有共同祖先**（本地是独立的 root 提交链），因此普通 push 会被
    #    `non-fast-forward` 拒绝。数据以本机为准，所以这里接受强推。
    #    用 `--force-with-lease`（而非 --force）保留"远端被别人改过就中止"的保护。
    #
    #    但 lease 要求本地 `refs/remotes/origin/main` 与远端当前值一致 ——
    #    本仓库 fetch 从没成功过，该 ref 一直是旧值，于是 lease 必然报
    #    `(stale info)` 而拒绝。所以推送前必须用 ls-remote 把基准校准到远端真值。
    if not _sync_remote_tracking_ref():
        print('[PUSH] lease 基准校准失败，仍尝试 force（数据以本机为准）', file=sys.stderr)

    attempts = [
        (['push', 'origin', 'main'], '普通'),
        (['push', '--force-with-lease', 'origin', 'main'], 'force-with-lease'),
        (['push', '--force', 'origin', 'main'], 'force'),
    ]
    last_err = ''
    for extra, tag in attempts:
        rc, out, err = _git_run(_git_auth_args() + extra, timeout=300, allow_kill=False)
        if rc == 0:
            print(f'[OK] Git pushed ({tag}): {message}')
            return
        last_err = (err or out).strip()[:300]
        print(f'[WARN] Git push {tag} 失败 (rc={rc}): {last_err}', file=sys.stderr)

    raise RuntimeError(f'git push 失败: {last_err}')

# ═══════════════ GIT 子进程安全执行（2026-09-16 新增）═══════════════
# 背景：本机到 GitHub 只有 ~20 KB/s。`subprocess.run(timeout=)` 在 Windows 上
# **只杀直接子进程**，git 拉起的 git-remote-https / index-pack 会变成孤儿继续
# 占着 .git 里的锁；而把 git stash 这类会改写 .git 内部结构的命令中途砍掉，
# 还可能让 `refs/` 目录整个消失 → 仓库变成 "not a git repository"。
# 因此这里统一走 Popen + 超时后 taskkill /T 回收整棵树的方式。
def _kill_tree(pid):
    """强杀进程及其所有子进程（Windows）。"""
    if sys.platform != 'win32':
        try:
            os.kill(pid, 9)
        except Exception:
            pass
        return
    try:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                       capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as _e:
        print(f'[GIT][WARN] taskkill 失败 pid={pid}: {_e}', file=sys.stderr)


def _git_run(args, cwd=None, env=None, timeout=120, allow_kill=True):
    """跑 git 命令，超时后**回收整棵进程树**。

    返回 (rc, stdout, stderr)；超时返回 rc=-9。
    输出按 utf-8 → gbk → latin-1 逐级解码 —— Windows 中文版 git 的报错是 GBK，
    而 Popen(text=True) 的 errors 参数不会作用于内部读取线程，会直接把
    UnicodeDecodeError 抛成难以定位的 TypeError。

    ⚠️ `allow_kill=False` 时超时也**不杀进程**：只放弃等待、直接返回。
    某些 git 操作（rebase 等）被强杀后会破坏 `.git` 内部结构（实测
    `refs/` 目录会被清掉 → 整个仓库报 "not a git repository"），
    这类命令宁可让它自己跑完也不杀。
    """
    # 每次 git 操作前都自愈 refs —— 便宜（几个 os.path.isdir），
    # 但能挡住「上一轮被杀的 git 留下的残缺状态」。
    _ensure_refs()

    cwd = cwd or DATA_DIR
    env = env or GIT_ENV
    cf = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        p = subprocess.Popen(['git'] + list(args), cwd=cwd, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=cf)
    except Exception as _e:
        return -1, '', f'Popen failed: {_e!r}'
    try:
        raw_out, raw_err = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        if allow_kill:
            print(f'[GIT][WARN] git {" ".join(args[:3])} 超时 {timeout}s，回收进程树…',
                  file=sys.stderr)
            _kill_tree(p.pid)
            try:
                raw_out, raw_err = p.communicate(timeout=15)
            except Exception:
                raw_out, raw_err = b'', b''
        else:
            # 不杀 —— 让它自己跑完。但我们不再等待，直接放弃本次调用。
            # 注意：这样会留下一个仍在运行的 git 进程，因此调用方必须理解
            # 「这一轮不同步远端」是可接受的（本机数据优先）。
            print(f'[GIT][WARN] git {" ".join(args[:3])} 超时 {timeout}s，'
                  f'按策略不杀进程、放弃等待（远端同步跳过，用本地数据继续）', file=sys.stderr)
            raw_out, raw_err = b'', b''
        rc = -9

    def _dec(b):
        if not b:
            return ''
        for enc in ('utf-8', 'gbk', 'latin-1'):
            try:
                return b.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return b.decode('utf-8', 'replace')

    return rc, _dec(raw_out), _dec(raw_err)


def _ensure_refs():
    """自愈：确保 .git/refs 骨架存在，并且 ref 真的**可读**。

    这是踩过坑的兜底 —— 一次被中途杀掉的 `git stash` / `git rebase` 让整个
    refs/ 目录消失，之后 git 一律报 "not a git repository"（其实 objects
    齐全、数据完好），只能手工重建。这里把重建逻辑固化下来。

    ⚠️ 本函数**绝不调用 `_git_run`**（否则 `_git_run` → `_ensure_refs` →
    `_git_run` 无限递归）。全部走纯文件系统判断。

    ── 2026-09-16 关键发现 ────────────────────────────────────────────
    **`git update-ref <ref>` 在 ref 的中间目录不存在时，会静默失败：
    返回 rc=0，但不创建任何文件。** 实测（git for Windows）：

        $ git update-ref refs/remotes/origin/main <sha>
        rc=0                                    ← 报告成功
        文件 .git/refs/remotes/origin/main 存在=False   ← 什么都没建
        $ git rev-parse refs/remotes/origin/main
        fatal: ambiguous argument ...           ← 读不到

        # 而手工 makedirs + open(...,'w') 写同一个路径 → rev-parse 立刻 rc=0

    这就是为什么 `git fetch` 会打印 `[new branch] main -> origin/main`
    却查不到该 ref、为什么 refs/ 目录一直是空的：fetch 内部走 update-ref，
    同样静默失败。所以本函数**必须**在写完后回读验证，不能只看 rc。
    ──────────────────────────────────────────────────────────────────
    """
    gitd = os.path.join(DATA_DIR, '.git')
    if not os.path.isdir(gitd):
        return False

    fixed = False
    for d in ('refs/heads', 'refs/tags', 'refs/remotes/origin'):
        p = os.path.join(gitd, *d.split('/'))
        if not os.path.isdir(p):
            try:
                os.makedirs(p, exist_ok=True)
                print(f'[GIT] 自愈：重建 {d}')
                fixed = True
            except Exception as _e:
                print(f'[GIT][WARN] 建目录失败 {d}: {_e}', file=sys.stderr)

    # HEAD 内容形如 "ref: refs/heads/main"，检查该 ref 文件是否存在
    try:
        head_ref = open(os.path.join(gitd, 'HEAD'), encoding='utf-8').read().strip()
    except Exception:
        head_ref = ''

    # ⚠️ 先读 packed-refs。git fetch / pack-refs 会把 ref 从 loose 文件
    # 迁进 packed-refs 并删掉 loose 文件 —— 如果只看「loose 文件在不在」，
    # 会把这种**正常状态**误判为缺失，然后用 packed-refs 的旧 sha 重建，
    # 结果每轮都把 fetch 刚更新的 origin/main **覆盖回旧值**（死循环）。
    packed_map = {}
    packed = os.path.join(gitd, 'packed-refs')
    if os.path.exists(packed):
        for line in open(packed, encoding='utf-8', errors='replace'):
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('^'):
                continue
            parts = line.split()
            if len(parts) == 2:
                packed_map[parts[1]] = parts[0]

    need = []
    if head_ref.startswith('ref: '):
        need.append(head_ref[5:].strip())
    need.append('refs/remotes/origin/main')

    def _loose_ok(ref):
        """loose ref 文件是否存在**且内容合法**。

        ⚠️ 光看存在性不够：如果文件是文本模式写的，Windows 会留下 '\r\n'，
        git 会判定为 "bad ref"（`git show-ref` 直接 rc=128）。这种情况必须
        当作"需要重建"处理，否则仓库一直处于半坏状态。
        """
        fp = os.path.join(gitd, *ref.split('/'))
        if not os.path.exists(fp):
            return False
        try:
            raw = open(fp, 'rb').read()
        except Exception:
            return False
        # 合法形式：40 位 hex + 单个 '\n'（不要 '\r'）
        return raw == raw.strip() + b'\n' and len(raw.strip()) == 40 \
            and all(c in b'0123456789abcdef' for c in raw.strip())

    missing = []
    for r in need:
        if _loose_ok(r):
            continue
        if r in packed_map and not os.path.exists(os.path.join(gitd, *r.split('/'))):
            continue                 # 已在 packed-refs 里 —— 正常，无需重建
        missing.append(r)

    if not missing:
        return fixed

    # ⚠️ remote-tracking ref 的 sha **优先取 FETCH_HEAD**：它才是最近一次
    # fetch 的真实结果。packed-refs 里的值往往是上一轮的旧值，用它会让
    # origin/main 永远停在旧提交。
    def _sha_of(ref):
        if ref == 'refs/remotes/origin/main':
            fp = os.path.join(gitd, 'FETCH_HEAD')
            if os.path.exists(fp):
                try:
                    txt = open(fp, encoding='utf-8', errors='replace').read().strip()
                    first = txt.split()[0] if txt.split() else ''
                    if len(first) == 40 and all(c in '0123456789abcdef' for c in first):
                        return first, 'FETCH_HEAD'
                except Exception:
                    pass
        if ref in packed_map:
            return packed_map[ref], 'packed-refs'
        return None, None

    wrote = 0
    for rel in missing:
        sha, src = _sha_of(rel)
        if not sha and rel == 'refs/remotes/origin/main':
            # 退一步：HEAD 自身的 sha 至少能让 git 认出仓库
            sha, src = packed_map.get('refs/heads/main'), 'packed-refs(heads/main)'
        if not sha:
            print(f'[GIT][WARN] refs 缺失 {rel} 且找不到可用 sha，无法自愈', file=sys.stderr)
            continue
        p = os.path.join(gitd, *rel.split('/'))
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            # ⚠️ 必须二进制写入：文本模式在 Windows 上会把 '\n' 变成 '\r\n'，
            #    而 git 要求 loose ref 以单个 '\n' 结尾，多出的 '\r' 会让
            #    ref 变成 "bad ref"（show-ref 直接 rc=128）。
            with open(p, 'wb') as f:
                f.write(sha.encode('ascii') + b'\n')
            # ⚠️ 回读验证 —— 目录缺失等情况下写入可能没生效
            if os.path.exists(p) and open(p, 'rb').read().strip().decode('ascii', 'replace') == sha:
                print(f'[GIT] 自愈：重建 {rel} = {sha[:8]} (源 {src})')
                fixed = True
                wrote += 1
            else:
                print(f'[GIT][WARN] 写入 {rel} 后回读校验失败', file=sys.stderr)
        except Exception as _e:
            print(f'[GIT][WARN] 写 {rel} 失败: {_e}', file=sys.stderr)

    return fixed


def _dirty_tracked():
    """已跟踪文件的改动路径（含已暂存与未暂存）。

    `git status --porcelain` 的格式是两列状态 + 空格 + 路径：
        ' M file'  工作区改（未暂存）
        'M  file'  已暂存
        'MM file'  暂存后又改
        'A  file'  新增已暂存
        'D  file'  删除已暂存
    任一一列非空都算「工作区不干净」，都必须纳入中转提交，
    否则 rebase 会以 `You have unstaged changes` 拒绝。
    （原实现只切 `l[3:]`，把 'M  x' 切成了 'x'，但没意识到
      ' A x' / 'A  x' 这些**已暂存**的也要一并处理。）
    """
    rc, out, _ = _git_run(['status', '--porcelain', '--untracked-files=no'], timeout=120)
    if rc != 0:
        return None
    files = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if ' -> ' in path:                       # 重命名 'R  old -> new'
            path = path.split(' -> ', 1)[1].strip()
        if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
            path = path[1:-1]
        if path:
            files.append(path)
    return files


def _commit_all_local(message):
    """把所有已跟踪改动提交成一次中转提交。

    返回 True = 工作区已干净（或本来就干净）；False = 仍不干净。
    用 `git add -A -- <files>` 而不是逐个 `add`，因为它同时覆盖
    「已暂存 / 未暂存 / 删除」三种状态。
    """
    files = _dirty_tracked()
    if files is None:
        print('[GIT][WARN] 无法读取工作区状态', file=sys.stderr)
        return False
    if not files:
        return True

    print(f'[GIT] 工作区有 {len(files)} 个已跟踪改动，先落地为本地中转提交')
    rc_a, _, err_a = _git_run(['add', '-A', '--', *files], timeout=300)
    if rc_a != 0:
        print(f'[GIT][WARN] add 失败：{err_a.strip()[:200]}', file=sys.stderr)
        return False

    rc_c, out_c, err_c = _git_run(['commit', '-m', message, '--no-verify'], timeout=300)
    if rc_c != 0:
        if 'nothing to commit' in (out_c + err_c):
            return True
        print(f'[GIT][WARN] 中转提交失败：{err_c.strip()[:250]}', file=sys.stderr)
        return False

    # 复核：提交后必须真的干净
    left = _dirty_tracked()
    if left:
        print(f'[GIT][WARN] 中转提交后仍有 {len(left)} 个改动未落地', file=sys.stderr)
        return False
    return True


def _ensure_git_identity():
    """确保仓库有提交身份。

    踩过的坑（2026-09-16）：新建/重建的克隆里既没有 global 也没有 local 的
    user.name / user.email，于是每一个 `git commit` 都 rc=128 报
    "Author identity unknown" —— 抓取全部正常、只有最后一步提交失败，
    表现为「跑了几分钟、日志很漂亮、数据一条没上去」。

    这里只写 **仓库本地** 配置，不动用户的 global 设置。
    """
    for key, val in (('user.name', 'cs2-runner'),
                     ('user.email', 'cs2-runner@localhost')):
        rc, out, _ = _git_run(['config', '--get', key], timeout=30)
        if rc != 0 or not out.strip():
            rc_s, _, err_s = _git_run(['config', key, val], timeout=30)
            if rc_s == 0:
                print(f'[GIT] 已补写仓库本地 {key} = {val}')
            else:
                print(f'[GIT][WARN] 写 {key} 失败: {err_s.strip()[:120]}', file=sys.stderr)


def _sync_remote_tracking_ref():
    """把 refs/remotes/origin/main 校准成**远端真实**的 sha。

    为什么需要（2026-09-16 实测）：
      `git push --force-with-lease` 会拿本地的 `refs/remotes/origin/main` 与远端
      当前值比对，不一致就拒绝并报 `! [rejected] main -> main (stale info)`。
      而这个仓库的 fetch 从来没成功过 —— 本地那个 ref 一直停在旧值
      （如 `25df639`），远端其实已是 `dbfcfde`，于是 lease 永远校验失败，
      强推通道被自己锁死。

    解法：用 `git ls-remote`（只读、不需要本地对象、4~5 秒）拿到远端真实 sha，
    再用纯文件系统写入本地 ref。这样 `--force-with-lease` 就能通过，
    同时**保留**了它的保护语义：若期间有别人推过，sha 变了，lease 仍会中止。

    写入用二进制模式 —— 文本模式在 Windows 上会产生 '\r\n'，git 会判为 bad ref。
    """
    rc, out, err = _git_run(_git_auth_args() + ['ls-remote', 'origin', 'main'],
                            timeout=120, allow_kill=False)
    if rc != 0:
        print(f'[GIT][WARN] ls-remote 失败 rc={rc}：{err.strip()[:160]}', file=sys.stderr)
        return False

    sha = ''
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == 'refs/heads/main' and len(parts[0]) == 40:
            sha = parts[0]
            break
    if not sha:
        print('[GIT][WARN] ls-remote 未返回 refs/heads/main', file=sys.stderr)
        return False

    gitd = os.path.join(DATA_DIR, '.git')
    rel = 'refs/remotes/origin/main'
    dst = os.path.join(gitd, *rel.split('/'))
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(sha.encode('ascii') + b'\n')
        if open(dst, 'rb').read().strip().decode('ascii', 'replace') == sha:
            print(f'[GIT] 校准 {rel} = {sha[:8]}（远端真实值）')
            return True
        print(f'[GIT][WARN] 校准 {rel} 后回读失败', file=sys.stderr)
    except Exception as _e:
        print(f'[GIT][WARN] 写 {rel} 失败：{_e}', file=sys.stderr)
    return False


def _repair_remote_ref():
    """把 origin/main 落成 loose ref（用 FETCH_HEAD / packed-refs 的 sha）。

    历史用途：`git fetch` 报告 `[new branch] main -> origin/main` 但 ref 实际
    没建（git for Windows 的 update-ref 在中间目录缺失时静默失败）。
    现已不再依赖 fetch；新代码用 `_sync_remote_tracking_ref()` 从 ls-remote
    取真实 sha。此函数保留作为无网络时的兜底。
    """
    gitd = os.path.join(DATA_DIR, '.git')
    ref = 'refs/remotes/origin/main'
    dst = os.path.join(gitd, *ref.split('/'))

    # 已能正常解析就不用管
    if os.path.exists(dst):
        return

    fh = os.path.join(gitd, 'FETCH_HEAD')
    sha = ''
    if os.path.exists(fh):
        try:
            first = open(fh, encoding='utf-8', errors='replace').read().strip().split()
            if first and len(first[0]) == 40 and all(c in '0123456789abcdef' for c in first[0]):
                sha = first[0]
        except Exception:
            sha = ''
    if not sha:
        # 退一步：用 packed-refs 里的 main
        try:
            for line in open(os.path.join(gitd, 'packed-refs'), encoding='utf-8', errors='replace'):
                line = line.strip()
                if line.endswith(' refs/heads/main'):
                    sha = line.split()[0]
                    break
        except Exception:
            sha = ''
    if not sha:
        print('[GIT][WARN] 无法确定 origin/main 的 sha，跳过补写', file=sys.stderr)
        return

    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # 二进制写入：避免 Windows 文本模式把 '\n' 写成 '\r\n'（会让 ref 变 bad ref）
        with open(dst, 'wb') as f:
            f.write(sha.encode('ascii') + b'\n')
        # 回读验证：目录缺失等场景下，写入可能"成功"但文件不在
        if os.path.exists(dst) and open(dst, 'rb').read().strip().decode('ascii', 'replace') == sha:
            print(f'[GIT] 补写 refs/remotes/origin/main = {sha[:8]}')
        else:
            print('[GIT][WARN] 补写 origin/main 后回读校验失败', file=sys.stderr)
    except Exception as _e:
        print(f'[GIT][WARN] 补写 origin/main 失败: {_e}', file=sys.stderr)


def git_sync_safe():
    """本地提交 + 直接 push，**不做 fetch / rebase**。

    ── 为什么彻底放弃 fetch/rebase（2026-09-16 实测结论）─────────────────
    原实现是「stash(已删) → fetch --depth=1 → rebase FETCH_HEAD」。逐条否掉：

    1. **fetch 在这个仓库里从来没成功落过对象**。反复观察到：
       - `git fetch --depth=1 origin main` 返回 rc=0，stderr 打印
         `* [new branch] main -> origin/main`，看起来成功；
       - 但 `git cat-file -t <FETCH_HEAD>` → `could not get object info`；
       - `git for-each-ref` → `missing object <sha> for refs/remotes/origin/main`；
       - `git fsck` → `error: refs/remotes/origin/main: invalid sha1 pointer`。
       即 fetch 只写了 FETCH_HEAD 和 pack 元数据，真实对象没下来。
       （pack 目录里躺着的 `tmp_pack_*` 残留也是同一个成因。）

    2. **rebase 是破坏 refs/ 的头号元凶**。rebase 会重写 refs/ 与索引，
       实测一旦被超时强杀，整个 `refs/` 目录会被清空，仓库立刻变成
       `fatal: not a git repository`（objects 与数据其实完好）。

    3. **远端数据比本地旧**。远端 changelog 停在 9/15 21:05，本地已到 9/16 00:38。
       fetch/rebase 过来的是**更旧**的数据，只会覆盖本地的新数据。

    4. 本地是 shallow clone，fsck 永远报浅边界处的 missing blob（固有特性）。

    结论：这条同步线收益为负。改为「本地独立提交 → 直接 push」，
    由 push 端负责把本地数据推上去。push 不需要远端对象在本地存在，
    因此完全绕开了上面 1~4 的所有问题。

    幂等且无阻塞：没有任何网络拉取，全部步骤都有超时且可安全强杀。
    """
    _ensure_refs()
    _ensure_git_identity()

    lock_path = os.path.join(DATA_DIR, '.git', 'index.lock')
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
            print('[GIT] Removed stale index.lock')
        except Exception:
            pass

    # HEAD 必须可解析（仓库骨架没坏）
    rc, _, err = _git_run(['rev-parse', '--verify', 'HEAD'], timeout=30)
    if rc != 0:
        print(f'[GIT][WARN] HEAD 不可解析（{err.strip()[:120]}），跳过 git 步骤', file=sys.stderr)
        return

    # 把工作区改动落成本地提交，保证后续 push 有内容可推。
    # 注意：这只是"落地"，不 push —— 真正的 push 由 push_all()/git_push_locally()
    # 在数据生成完之后统一做（那时才知道哪些文件真的变了）。
    if not _commit_all_local(f'wip: local snapshot {time.strftime("%Y-%m-%d %H:%M")}'):
        print('[GIT][WARN] 本地中转提交未完成，继续跑数据更新（不影响推送）', file=sys.stderr)


# ═══════════════ MAIN ═══════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    # ── 静默同步 Git（带超时保护，绝不死等）──
    try:
        git_sync_safe()
    except Exception as e:
        print(f'[GIT] Sync failed: {e}', file=sys.stderr)

    # 兜底扫描：修复 git sync 残留的冲突标记
    _fix_corrupted_jsons()

    print(f'=== CS2 Dashboard Update ({mode}) ===')

    # ── 独立价格历史记录器（history 模式）──
    # 供后续 Kronos 微调积累长序列（目标每标的 >=512 点，填满 512 步上下文）。
    # 设计：重新抓 ECO 现价落 eco 通道 + 从 eco_tracked.json 缓存落 buff/yy 通道，
    #       **不动 prices 周期**、不写 market.json、不 push。
    # 频率由 updater_daemon.py 的 HISTORY_INTERVAL 控制（默认 3 小时，可用环境变量压到 1h/2h）。
    # 覆盖：eco 仅 ~500 件活跃在售；buff/yy 借 eco_tracked.json 缓存覆盖 5000+ 件（零额外 API 成本）。
    if mode == 'history':
        try:
            import price_db
            _seed_db_if_needed(price_db)
            now = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())
            # 1) 重新抓 ECO 现价（活跃在售 ~500 件）→ eco 通道
            tp = os.path.join(DATA_DIR, 'eco_tracked.json')
            hn_list = []
            if os.path.exists(tp):
                for it in (read_json(tp) or []):
                    hn = it.get('HashName', '') or ''
                    if hn:
                        hn_list.append(hn)
            if not hn_list:
                mp = os.path.join(DATA_DIR, 'market.json')
                if os.path.exists(mp):
                    for r in (read_json(mp) or {}).get('recommendations', {}).get('all', []):
                        hn = r.get('hash_name', '') or ''
                        if hn:
                            hn_list.append(hn)
            hn_list = list(dict.fromkeys(hn_list))
            records = []
            if hn_list:
                print(f'[HISTORY] 重新抓取 {len(hn_list)} 件 ECO 现价...')
                prices = fetch_eco_prices(hn_list)
                for hn, p in prices.items():
                    if p > 0:
                        records.append((hn, 'eco', now, p))
            eco_n = len(records)
            # 2) 从 eco_tracked.json 缓存落 buff/yy（覆盖 5000+ 件，零额外 API 成本）
            buff_n = yy_n = 0
            if os.path.exists(tp):
                for it in (read_json(tp) or []):
                    hn = it.get('HashName', '') or ''
                    if not hn:
                        continue
                    bp = float(it.get('buff_sell', 0) or 0)
                    if bp > 0:
                        records.append((hn, 'buff', now, bp)); buff_n += 1
                    yp = float(it.get('yyyp_sell', 0) or 0)
                    if yp > 0:
                        records.append((hn, 'yy', now, yp)); yy_n += 1
            written = price_db.record_batch(records) if records else 0
            keep = int(os.environ.get('PRICE_HIST_KEEP_DAYS') or '365')
            price_db.trim_old_data(keep)
            print(f'[HISTORY] 落库 {written} 条（eco {eco_n} / buff {buff_n} / yy {yy_n}），保留 {keep} 天')
        except Exception as e:
            print(f'[HISTORY] 失败: {e}', file=sys.stderr)
        return

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
                        steam_ok = 0
                        for item in tracked:
                            hn = item.get('HashName', '')
                            if hn and hn in batch_prices:
                                bp = batch_prices[hn]
                                # ⚠ 2026-09-15：保留双源原值，供 normalize 层做真·交叉验证。
                                #   CSQAQ 的全量值写进 _csqaq_buff；SteamDT 稍后会覆盖 buff_sell，
                                #   所以必须在这里先把 CSQAQ 原值单独存一份，否则丢失。
                                if bp.get('buff_sell', 0) > 0:
                                    item['_csqaq_buff'] = bp['buff_sell']
                                    item['buff_sell'] = bp['buff_sell']
                                    item['buff_source'] = 'BUFF'
                                item['buff_sell_num'] = bp.get('buff_sell_num', 0) or item.get('buff_sell_num', 0)
                                item['yyyp_sell'] = bp.get('yyyp_sell', 0)
                                item['yyyp_sell_num'] = bp.get('yyyp_sell_num', 0)
                                # ★ 独立市场基准价：Steam 社区市场（与 BUFF/悠悠 非同源）
                                #   没有它 → ref_price 覆盖率 0% → 溢价永远算不出来（假指标）
                                if bp.get('steam_sell', 0) > 0:
                                    item['steam_sell'] = bp['steam_sell']
                                    item['steam_sell_num'] = bp.get('steam_sell_num', 0)
                                    steam_ok += 1
                                merged += 1
                        print(f'[CSQAQ] Batch merged: {merged} items (独立基准价 steam_sell: {steam_ok})')
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
                    # ⚠ 2026-09-18：SteamDT batch 配额有限（实测已 4005 耗尽），
                    #   改为「推荐候选池优先」排序 → 配额先保证会进推荐的标的拿到买卖盘。
                    _cand, _rest = [], []
                    for it in tracked:
                        _h = it.get('HashName', '')
                        if not _h:
                            continue
                        try:
                            _is_cand = (float(it.get('Price') or 0) >= 20
                                        and int(it.get('SellingTotal') or 0) >= REC_MIN_SELLING)
                        except Exception:
                            _is_cand = False
                        (_cand if _is_cand else _rest).append(_h)
                    all_hn = _cand + _rest
                    # ⚠ 2026-09-18：批量接口限「每分钟 1 次、单次≤100 件」→ 全池 4779 件需 48 批≈52 分钟，
                    #   期间任何并发调用都会撞 4005。改为默认只取候选池优先的前 N 件（约 14 分钟）。
                    _cap = int(os.environ.get('STEAMDT_MAX_ITEMS') or '1400')
                    if len(all_hn) > _cap:
                        print('[SteamDT] 批量限速 1次/分(≤100件) → 本轮取前 %d 件（候选池优先），其余下轮补 '
                              '（STEAMDT_MAX_ITEMS 可调）' % _cap)
                        all_hn = all_hn[:_cap]
                    print('[SteamDT] Fetching multi-platform prices for %d tracked items (候选池优先 %d 件)...'
                          % (len(all_hn), len(_cand)))
                    full_prices = fetch_steamdt_prices(all_hn, verbose=False)
                    if full_prices and len(full_prices) > len(buff_prices):
                        buff_prices = full_prices  # 用全量数据替换
                        # 合并到 eco_tracked.json
                        merged = 0
                        for item in tracked:
                            hn = item.get('HashName', '')
                            if hn and hn in full_prices:
                                bp = full_prices[hn]
                                # ⚠ 2026-09-15：SteamDT 会覆盖 buff_sell。
                                #   先把 SteamDT 原值单独存一份到 _steamdt_buff，
                                #   否则 CSQAQ 的 _csqaq_buff 就成了孤儿，双源无法交叉验证。
                                if bp.get('buff_sell', 0) > 0:
                                    item['_steamdt_buff'] = bp['buff_sell']
                                    item['_steamdt_src'] = bp.get('buff_source', '')
                                item['buff_sell'] = bp.get('buff_sell', 0)
                                item['buff_buy'] = bp.get('buff_buy', 0)
                                item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                                item['platforms'] = bp.get('platforms', {})
                                merged += 1
                        write_json(tracked_path, tracked)
                        print(f'[SteamDT] Merged {merged}/{len(tracked)} items (full catalog + platforms)')
                        # ⚠ 2026-09-18：SteamDT 是唯一能提供「BUFF 求购(biddingPrice/Count)」的源，
                        #   而 eco_tracked.json 会被 prices 周期重写清空 → 必须同步落旁路文件。
                        try:
                            if save_csqaq_boards(full_prices):
                                print('[SteamDT] 买盘字段已写入 csqaq_boards.json（旁路持久化）')
                        except Exception as _pe:
                            print('[SteamDT] 旁路写入失败: %s' % _pe, file=sys.stderr)
                        
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

            # ── 买盘补全（CSQAQ info/chart 优先 / SteamDT 兜底）→ 再算一轮，让 B1/B3 生效 ──
            # 背景：评分 B1「买卖盘强度」(35分) / B3「买盘贴价」(25分) 依赖 BUFF 求购数据，
            #   缺失时按中性 0.5 计 → BUFF 维度区分度弱。此处对初次入选的标的补齐求购数据后重算。
            # 关掉：环境变量 SKIP_BUY_FILL=1
            try:
                import buy_fill
                _bnames = [r.get('hash_name') for r in recs.get('all', []) if r.get('hash_name')]
                if os.environ.get('SKIP_BUY_FILL') != '1' and _bnames:
                    _filled = buy_fill.fill_buy_data(_bnames, verbose=True)
                    if _filled:
                        _before = {r.get('hash_name'): r.get('score') for r in recs.get('all', [])}
                        recs = generate_recommendations(alerts=alerts_data, steamdt_prices=buff_prices)
                        _moved = sum(1 for r in recs.get('all', [])
                                     if _before.get(r.get('hash_name')) != r.get('score'))
                        _eco2 = sum(1 for r in recs.get('all', []) if r.get('tag') == 'eco')
                        _buff2 = sum(1 for r in recs.get('all', []) if r.get('tag') == 'buff')
                        print('[BUY] 补买盘 %d 件后重算：%d 条分数变化 | ECO=%d BUFF=%d'
                              % (len(_filled), _moved, _eco2, _buff2))
            except Exception as _be:
                print('[BUY] 买盘补全失败（非致命）: %s' % _be, file=sys.stderr)

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
                    # 保留期：默认从 90 天放宽到 365 天 —— 更长历史是后续微调 Kronos 的前提
                    # （实测每个标的只有约 51 根日线，不足以支撑时序基础模型的领域自适应）
                    price_db.trim_old_data(int(os.environ.get('PRICE_HIST_KEEP_DAYS') or '365'))
                    # Inject price history from SQLite into rec items
                    for r in recs.get('all', []):
                        hn = r.get('hash_name', '')
                        if not hn: continue
                        try:
                            # 同时注入时间戳：前端折线图要显示真实采样区间
                            # （取的是「最近 60 个采样点」，实测约 3~4 次/天，≠30 天）
                            history = price_db.get_history(hn, channel='eco')
                            if history:
                                r['eco_history'] = [h['price'] for h in history[-60:]]
                                r['eco_history_ts'] = [h.get('ts', '') for h in history[-60:]]
                                # 趋势涨跌：同一份历史算 1/7/30 日
                                # （这两个字段以前从未被写入 → 前端「1日/7日/30日」恒为「—」）
                                for _d, _k in ((1, 'rate_1'), (7, 'rate_7'), (30, 'rate_30')):
                                    _v = _rate_from_hist(history, _d)
                                    if _v is not None:
                                        r[_k] = _v
                                # 日线（按天聚合）：让「近30日」这个说法名副其实
                                try:
                                    _dd = price_db.get_daily_averages(hn, channel='eco', days=30)
                                    if _dd and len(_dd) >= 3:
                                        r['eco_daily'] = [x['avg'] for x in _dd]
                                        r['eco_daily_ts'] = [x['day'] for x in _dd]
                                except Exception:
                                    pass
                            history = price_db.get_history(hn, channel='buff')
                            if history:
                                r['multi_history'] = [h['price'] for h in history[-60:]]
                                r['multi_history_ts'] = [h.get('ts', '') for h in history[-60:]]
                            history = price_db.get_history(hn, channel='yy')
                            if history:
                                r['yyyp_history'] = [h['price'] for h in history[-60:]]
                                r['yyyp_history_ts'] = [h.get('ts', '') for h in history[-60:]]
                        except Exception as _e:
                            print(f'[WARN] 注入悠悠历史失败: {_e}', file=sys.stderr)
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
                    # ── Kronos 价格预测（推荐池前10 + AI 精选；频率 = 推荐板块更新频率）──
                    if run_kronos_forecast() is not None:
                        dirty_files.add('ai_forecast.json')
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

    # ── FirePulse 大盘（饰品指数/成交额/贪婪指数）──
    try:
        import firepulse
        if firepulse.enabled():
            _ov = firepulse.fetch_overview()
            if _ov:
                write_json(os.path.join(DATA_DIR, 'market_overview.json'), _ov)
                dirty_files.add('market_overview.json')
                _i = _ov['index']
                # 板块数据（单次请求拿全部板块）
                try:
                    _sec = firepulse.fetch_sectors(category_type=-1, limit=24)
                    if _sec:
                        write_json(os.path.join(DATA_DIR, 'market_sectors.json'), {
                            'sectors': _sec,
                            'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'source': 'firepulse',
                        })
                        dirty_files.add('market_sectors.json')
                        print('[FirePulse] 板块: %d 个' % len(_sec))
                except Exception as _e4:
                    print('[FirePulse] 板块获取失败: %s' % _e4, file=sys.stderr)

                # 大盘时间序列（供前端画走势图）
                try:
                    firepulse.append_overview_history(
                        _ov, os.path.join(DATA_DIR, 'market_overview_history.json'))
                    dirty_files.add('market_overview_history.json')
                except Exception as _e2:
                    print('[FirePulse] 大盘历史追加失败: %s' % _e2, file=sys.stderr)

                # 持仓精确化：用 10 平台价补充持仓数据（仅 all 模式，控制额度消耗）
                if mode in ('all',):
                    try:
                        _hp = os.path.join(DATA_DIR, 'holdings.json')
                        _h = read_json(_hp)
                        if isinstance(_h, dict) and _h.get('items'):
                            _cp = os.path.join(DATA_DIR, 'firepulse_ids.json')
                            _c = firepulse.load_id_cache(_cp)
                            _n = firepulse.enrich_items(_h['items'], _c, limit=120)
                            if _n:
                                firepulse.save_id_cache(_cp, _c)
                                write_json(_hp, _h)
                                dirty_files.update(['holdings.json', 'firepulse_ids.json'])
                                print('[FirePulse] 持仓精确化: %d 件已补充多平台数据' % _n)
                    except Exception as _e3:
                        print('[FirePulse] 持仓精确化失败: %s' % _e3, file=sys.stderr)

                print('[FirePulse] 大盘: 指数 %.2f (%.2f%%), 贪婪 %.1f(%s)' % (
                    _i.get('current') or 0, _i.get('change_pct') or 0,
                    (_ov['greedy'].get('value') or 0), (_ov['greedy'].get('label') or '')))
        else:
            print('[FirePulse] 未配置 FIREPULSE_KEY，跳过大盘')

        # 板块数据（列表 + 热门板块涨跌）
        if firepulse.enabled():
            try:
                _sec = firepulse.fetch_sector_overview(top_n=10, kline_for_top=24)
                if _sec:
                    write_json(os.path.join(DATA_DIR, 'sectors.json'), _sec)
                    dirty_files.add('sectors.json')
                    print('[FirePulse] 板块: 共 %d 个, 取到涨跌 %d 个' % (
                        len(_sec['list']), _sec.get('enriched', 0)))
            except Exception as _e:
                print('[FirePulse] 板块失败: %s' % _e, file=sys.stderr)

            # 大盘时序（每小时一条，累积成走势）
            try:
                _hp = os.path.join(DATA_DIR, 'market_overview_history.json')
                _hist, _added = firepulse.append_overview_history(_ov, _hp)
                if _added:
                    dirty_files.add('market_overview_history.json')
                    print('[FirePulse] 大盘历史: +1 条，共 %d 条' % len(_hist or []))
            except Exception as _e:
                print('[FirePulse] 大盘历史失败: %s' % _e, file=sys.stderr)

            # 持仓精确化（多平台价 + 存世量 + 30 日涨跌）
            try:
                _hp2 = os.path.join(DATA_DIR, 'holdings.json')
                _h2 = read_json(_hp2)
                _items2 = (_h2 or {}).get('items', []) if isinstance(_h2, dict) else []
                if _items2:
                    _cnt = firepulse.enrich_items(_items2, id_cache={}, max_items=40)
                    if _cnt:
                        write_json(_hp2, _h2)
                        dirty_files.add('holdings.json')
                        print('[FirePulse] 持仓精确化: %d/%d 项' % (_cnt, len(_items2)))
            except Exception as _e:
                print('[FirePulse] 持仓精确化失败: %s' % _e, file=sys.stderr)
    except Exception as _e:
        print('[FirePulse] 大盘生成失败: %s' % _e, file=sys.stderr)

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
        except Exception as _e:
            print(f'[WARN] 读取 price_db 统计失败: {_e}', file=sys.stderr)
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
    
    _ai_stats = []   # 各阶段耗时/结果，最后写 ai_meta.json

    def _ai_call_with_rate_limit(func, name):
        """AI 调用限流保护：确保两次调用间隔 >= 8 秒，遇到 429 重试 3 次；并记录阶段耗时"""
        _q = name in ('Market insight', 'Recommendations')
        elapsed = time.time() - _last_ai_call[0]
        if elapsed < 8:
            wait = 8 - elapsed
            print(f'[AI] Rate limit wait {wait:.0f}s...')
            time.sleep(wait)
        for attempt in range(3):
            _t0 = time.time()
            try:
                func()
                _ai_stats.append({'stage': name, 'sec': round(time.time() - _t0, 1), 'ok': True,
                                  'provider': _ai_provider(_q), 'model': _ai_model_name(_q)})
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
                _ai_stats.append({'stage': name, 'sec': round(time.time() - _t0, 1), 'ok': False,
                                  'err': str(e)[:120], 'provider': _ai_provider(_q)})
                _last_ai_call[0] = time.time()
                return
        print(f'[AI] {name} failed after 3 retries (rate limit)', file=sys.stderr)
        _last_ai_call[0] = time.time()
    
    # ═════ ── AI 开关：SKIP_AI=1 时跳过全部大模型调用 ── ═════
    # 用于高频价格线（update-prices workflow）：只刷价格/评分/异动，
    # 不消耗智谱额度，从而可以高频跑。AI 分析由低频的 update-all 负责。
    if os.environ.get('SKIP_AI') == '1':
        print('[AI] SKIP_AI=1 -> 跳过全部 AI 分析（仅更新价格与评分数据）')
    else:
        _ai_call_with_rate_limit(generate_ai_analysis, 'Analysis')
        _ai_call_with_rate_limit(generate_ai_daily_report, 'Daily report')
        _ai_call_with_rate_limit(generate_ai_anomaly, 'Anomaly')
        _ai_call_with_rate_limit(generate_ai_stock_picks, 'Stock picks')
        _ai_call_with_rate_limit(generate_ai_market_insight, 'Market insight')
        _ai_call_with_rate_limit(generate_ai_news_impact, 'News impact')
        _ai_call_with_rate_limit(generate_ai_recommendations, 'Recommendations')
        # ── 阶段耗时汇总（便于观察本地化后的周期变化）──
        try:
            _used = round(sum(x['sec'] for x in _ai_stats), 1)
            _okc = sum(1 for x in _ai_stats if x.get('ok'))
            write_json(os.path.join(DATA_DIR, 'ai_meta.json'), {
                'date': time.strftime('%Y-%m-%d %H:%M'),
                'total_sec': _used,
                'ok': _okc,
                'failed': len(_ai_stats) - _okc,
                'provider_fast': _ai_provider(False),
                'provider_quality': _ai_provider(True),
                'quality_model': _ai_model_name(True),
                'cloud_fallback': str(os.environ.get('AI_FALLBACK_CLOUD', '1')).strip() != '0',
                'stages': _ai_stats,
            })
            print('[AI] 阶段耗时 %.0fs（成功 %d/%d）: %s' % (
                _used, _okc, len(_ai_stats),
                ' | '.join('%s %.0fs%s' % (x['stage'], x['sec'], '' if x.get('ok') else '✗') for x in _ai_stats)))
        except Exception as _ae:
            print('[AI] 写 ai_meta.json 失败: %s' % _ae, file=sys.stderr)

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
