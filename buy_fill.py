# -*- coding: utf-8 -*-
"""买盘补全：CSQAQ info/chart 优先 → SteamDT 兜底。

为什么这个顺序：
  · CSQAQ /api/v1/info/chart：key=buy_price/buy_num、platform=1(BUFF)，
    **未标注企业权限**、返回历史时序，速度快（无每分钟 1 次限制）；
  · SteamDT：只有当前值，且批量接口限「每分钟 1 次」（慢但稳）→ 作为兜底，
    用于 CSQAQ 拿不到（无 goodId / 接口异常）的标的。

产出：写入 csqaq_boards.json（旁路，prices 周期不会清空），键与既有口径一致：
      buff_buy（求购价）、buff_buy_num（求购数量）、buy_src（来源，便于排查）。
"""
import os, sys, json, time

REPO = os.environ.get('CS2_REPO') or r'C:\Users\Lenovo\cs2-runner-local'

# CSQAQ chart 的参数（BUFF=1；求购价/求购数量）
_PLATFORM = int(os.environ.get('BUY_PLATFORM') or '1')
_PERIOD = int(os.environ.get('BUY_PERIOD') or '7')
_SLEEP = float(os.environ.get('BUY_SLEEP') or '0.35')
MAX_ITEMS = int(os.environ.get('BUY_FILL_CAP') or '60')


def _csqaq_call(path, body, token):
    sys.path.insert(0, REPO)
    import recommend
    return recommend.http_post_raw('https://api.csqaq.com' + path, body,
                                   headers={'ApiToken': token}, timeout=25)


def _last_positive(series):
    for v in reversed(series or []):
        if isinstance(v, (int, float)) and v > 0:
            return v
    return None


def _csqaq_buy(hash_names, token, verbose):
    """CSQAQ 优先：批量取 goodId → 逐件取求购价/求购数量。"""
    got = {}
    if not token:
        if verbose:
            print('[BUY] 无 CSQAQ token，跳过优先通道')
        return got
    # ① goodId（单批 ≤50）
    gid = {}
    for i in range(0, len(hash_names), 50):
        batch = hash_names[i:i + 50]
        try:
            r = _csqaq_call('/api/v1/goods/getPriceByMarketHashName',
                            {'marketHashNameList': batch}, token)
            for k, v in ((r.get('data') or {}).get('success') or {}).items():
                if v.get('goodId'):
                    gid[k] = v['goodId']
        except Exception as e:
            if verbose:
                print('[BUY] CSQAQ goodId 批失败: %s' % str(e)[:90], file=sys.stderr)
        time.sleep(_SLEEP)
    # ② 求购价 / 求购数量
    for hn, g in gid.items():
        row = {}
        for key, dst in (('buy_price', 'buff_buy'), ('buy_num', 'buff_buy_num')):
            try:
                r = _csqaq_call('/api/v1/info/chart',
                                {'good_id': g, 'key': key, 'platform': _PLATFORM,
                                 'period': _PERIOD, 'style': 'all_style'}, token)
                val = _last_positive((r.get('data') or {}).get('main_data'))
                if val is not None:
                    row[dst] = float(val) if dst == 'buff_buy' else int(val)
            except Exception as e:
                if verbose:
                    print('[BUY] CSQAQ chart %s %s 失败: %s' % (hn[:22], key, str(e)[:70]), file=sys.stderr)
            time.sleep(_SLEEP)
        if row:
            row['buy_src'] = 'csqaq_chart'
            got[hn] = row
    if verbose:
        print('[BUY] CSQAQ 优先通道: %d/%d 件拿到买盘' % (len(got), len(hash_names)))
    return got


def _steamdt_fallback(missing, verbose):
    """SteamDT 兜底：当前值（自动走 single≤32 / batch，含限流占坑）。"""
    out = {}
    if not missing:
        return out
    try:
        sys.path.insert(0, REPO)
        import update as U
        sp = U.fetch_steamdt_prices(missing, verbose=verbose)
    except Exception as e:
        if verbose:
            print('[BUY] SteamDT 兜底失败: %s' % str(e)[:120], file=sys.stderr)
        return out
    for hn, bp in (sp or {}).items():
        row = {}
        if bp.get('buff_buy'):
            row['buff_buy'] = float(bp['buff_buy'])
        if bp.get('buff_buy_num'):
            row['buff_buy_num'] = int(bp['buff_buy_num'])
        if bp.get('buff_sell'):
            row['buff_sell'] = float(bp['buff_sell'])
        if bp.get('buff_sell_num'):
            row['buff_sell_num'] = int(bp['buff_sell_num'])
        if bp.get('platforms'):
            row['platforms'] = bp['platforms']
        if row:
            row['buy_src'] = 'steamdt'
            out[hn] = row
    if verbose:
        print('[BUY] SteamDT 兜底通道: %d/%d 件拿到买盘' % (len(out), len(missing)))
    return out


def fill_buy_data(hash_names, verbose=True):
    """主入口：返回并落盘 {hash_name: {buff_buy, buff_buy_num, buy_src, ...}}。"""
    names = [n for n in (hash_names or []) if n][:MAX_ITEMS]
    if not names:
        return {}
    t0 = time.time()
    token = ''
    try:
        for line in open(os.path.join(REPO, 'local_keys.env'), encoding='utf-8'):
            line = line.strip()
            if line.startswith('CSQ_API_TOKEN'):
                token = line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

    out = _csqaq_buy(names, token, verbose)

    # 兜底条件：完全没拿到，或没拿到求购数量
    missing = [n for n in names
               if not out.get(n) or not out[n].get('buff_buy_num')]
    if missing:
        out.update(_steamdt_fallback(missing, verbose))

    # 落旁路（逐键合并，保留既有其他字段）
    if out:
        try:
            sys.path.insert(0, REPO)
            import update as U
            U.save_csqaq_boards(out)
        except Exception as e:
            print('[BUY] 落旁路失败: %s' % str(e)[:120], file=sys.stderr)
    if verbose:
        print('[BUY] 合计 %d/%d 件买盘（%.0fs，CSQAQ优先+SteamDT兜底）'
              % (len(out), len(names), time.time() - t0))
    return out


if __name__ == '__main__':
    argv = sys.argv[1:]
    if argv and os.path.exists(argv[0]):
        mkt = json.load(open(argv[0], encoding='utf-8'))
        ns = [r.get('hash_name') for r in (mkt.get('recommendations') or {}).get('all') or []]
    else:
        ns = argv
    print(json.dumps(fill_buy_data(ns), ensure_ascii=False)[:800])
