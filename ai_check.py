#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI provider 自检 —— 装完 Ollama 或改了环境变量后跑这个

用法:
    python ai_check.py              # 检查当前配置 + 各 provider 连通性 + 最小调用
    python ai_check.py --fast       # 额外验证「高频任务」链路
    python ai_check.py --quality    # 额外验证「质量敏感」链路

环境变量（都可在 local_keys.env 里配）:
    AI_PROVIDER_QUALITY=zhipu|ollama   质量敏感任务（买入推荐、市场洞察）
    AI_PROVIDER_FAST=zhipu|ollama      高频低价值（持仓/日报/异动/抄底/新闻）
    OLLAMA_HOST=http://127.0.0.1:11434
    OLLAMA_MODEL=qwen2.5:7b-instruct
    OLLAMA_NUM_CTX=8192                ★ 必须显式设：默认 2048 会静默截断长 prompt
    ZHIPU_MODEL=glm-4-flash
"""
import os, sys, json, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(HERE, 'local_keys.env'), encoding='utf-8') if os.path.exists(os.path.join(HERE, 'local_keys.env')) else []:
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, HERE)
os.chdir(HERE)
import update   # noqa: E402

print('=' * 64)
print('任务分类解析')
print('  质量敏感 (推荐/洞察) : provider=%-8s model=%s' % (update._ai_provider(True), update._ai_model_name(True)))
print('  高频低价值 (持仓等)  : provider=%-8s model=%s' % (update._ai_provider(False), update._ai_model_name(False)))
print('  OLLAMA_HOST          :', update.OLLAMA_HOST)
print('  OLLAMA_NUM_CTX       :', update.OLLAMA_NUM_CTX)
print('  智谱 key             :', '已配置' if update.ZHIPU_KEY else '★ 未配置')
print('=' * 64)

# ── Ollama 服务探活 ──
if 'ollama' in (update._ai_provider(True), update._ai_provider(False)):
    print('\n[Ollama] 探活', update.OLLAMA_HOST)
    try:
        with urllib.request.urlopen(update.OLLAMA_HOST + '/api/tags', timeout=6) as r:
            d = json.loads(r.read().decode('utf-8', 'replace'))
        names = [m.get('name') for m in (d.get('models') or [])]
        print('  ✓ 服务在线，本地模型 %d 个' % len(names))
        for n in names[:10]:
            print('     -', n)
        if update.OLLAMA_MODEL not in names:
            print('  ⚠ 目标模型 %s 不在列表，先执行: ollama pull %s' % (update.OLLAMA_MODEL, update.OLLAMA_MODEL))
    except Exception as e:
        print('  ✗ 不可达：%s' % str(e)[:120])
        print('    → 装好 Ollama 并确保服务在跑（托盘图标常驻），或改 OLLAMA_HOST')

# ── 最小调用 ──
def smoke(quality, tag):
    prov = update._ai_provider(quality)
    print('\n[%s] 最小调用  provider=%s model=%s' % (tag, prov, update._ai_model_name(quality)))
    t0 = time.time()
    txt = update._ai_call([{'role': 'user', 'content': '只回复两个字：正常'}],
                          max_tokens=32, temperature=0.1, quality=quality, timeout=60)
    if txt:
        print('  ✓ 返回（%.1fs）: %s' % (time.time() - t0, txt.replace('\n', ' ')[:80]))
        return True
    print('  ✗ 无返回（%.1fs）—— 看上面的错误行' % (time.time() - t0))
    return False

ok = True
if '--fast' in sys.argv or '--all' in sys.argv:
    ok &= smoke(False, '高频任务')
if '--quality' in sys.argv or '--all' in sys.argv:
    ok &= smoke(True, '质量敏感')

print('\n' + '=' * 64)
print('结论:', '全部可用' if ok else '有链路不可用（见上）')
print('提示：域名/DNS 与端口需放行本机回环；Ollama 仅本机可用，站点是静态页不受影响。')
