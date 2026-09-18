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
# 自适应节流：429 越多放得越慢，成功后逐步恢复（避免固定节流要么被限、要么过慢）
_pace = [_SLEEP]
_HIST_PATH = os.path.join(REPO, 'outputs', 'supply_history.json')


def _bump_pace():
    _pace[0] = min(5.0, _pace[0] * 1.8)


def _ease_pace():
    _pace[0] = max(_SLEEP, _pace[0] * 0.85)


def _pace_sleep():
    time.sleep(_pace[0])


def _save_supply_history(updates):
    """P2：存世量 180 天历史持久化（逐日去重、每件保留最近 200 天）→ outputs/supply_history.json"""
    if not updates:
        return
    try:
        os.makedirs(os.path.dirname(_HIST_PATH), exist_ok=True)
        db = {}
        if os.path.exists(_HIST_PATH):
            with open(_HIST_PATH, encoding='utf-8') as f:
                db = json.load(f) or {}
        for hn, series in updates.items():
            d = db.get(hn) or {}
            d.update(series)
            if len(d) > 200:
                for k in sorted(d)[:-200]:
                    d.pop(k, None)
            db[hn] = d
        with open(_HIST_PATH, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False)
        print('[BUY] 存世量历史已更新 %d 件 → supply_history.json' % len(updates))
    except Exception as e:
        print('[BUY] 历史持久化失败: %s' % str(e)[:100], file=sys.stderr)
MAX_ITEMS = int(os.environ.get('BUY_FILL_CAP') or '60')


def _csqaq_call(path, body, token):
    sys.path.insert(0, REPO)
    import recommend
    r = recommend.http_post_raw('https://api.csqaq.com' + path, body,
                                headers={'ApiToken': token}, timeout=25, rl_cb=_bump_pace)
    _ease_pace()
    return r


def _csqaq_get(url, token):
    sys.path.insert(0, REPO)
    import update
    if not url.startswith('http'):
        url = 'https://api.csqaq.com' + url   # ⚠ 必须补域名：http_get 不接受相对路径
    r = update.http_get(url, headers={'ApiToken': token}, timeout=20, rl_cb=_bump_pace)
    _ease_pace()
    return r


def _last_positive(series):
    for v in reversed(series or []):
        if isinstance(v, (int, float)) and v > 0:
            return v
    return None


def _csqaq_buy(hash_names, token, verbose):
    """CSQAQ 优先：批量取 goodId → 逐件取求购价/求购数量。"""
    got = {}
    out_meta = {}          # 由调用方合并进返回值（留痕 CSQAQ 在售价等）
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
                # 顺带留痕 CSQAQ 自家的在售价/多平台价（供跨源校验与跨市场参考）
                _row = {}
                if v.get('buffSellPrice'):
                    _row['_csqaq_buff'] = float(v['buffSellPrice'])
                    _row['buff_sell'] = float(v['buffSellPrice'])
                if v.get('buffSellNum'):
                    _row['buff_sell_num'] = int(v['buffSellNum'])
                if v.get('yyypSellPrice'):
                    _row['yyyp_sell'] = float(v['yyypSellPrice'])
                if v.get('yyypSellNum'):
                    _row['yyyp_sell_num'] = int(v['yyypSellNum'])
                if v.get('steamSellPrice'):
                    _row['steam_sell'] = float(v['steamSellPrice'])
                if v.get('steamSellNum'):
                    _row['steam_sell_num'] = int(v['steamSellNum'])
                if _row:
                    out_meta.setdefault(k, {}).update(_row)
        except Exception as e:
            if verbose:
                print('[BUY] CSQAQ goodId 批失败: %s' % str(e)[:90], file=sys.stderr)
        _pace_sleep()
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
            _pace_sleep()
        if row:
            row['buy_src'] = 'csqaq_chart'
            got[hn] = row
    for _hn, _row in (out_meta or {}).items():
        got.setdefault(_hn, {}).update(_row)
    if verbose:
        print('[BUY] CSQAQ 优先通道: %d/%d 件拿到买盘' % (len(got), len(hash_names)))
    return got, gid


def _csqaq_supply(gid_map, token, verbose):
    """真实存世量（近180天走势）→ n_supply_real + supply_chg7。

    ⚠ 现有「存世量」是 eco_selling（在售件数）代理，实测与真实值差 100~1000 倍。
    """
    out = {}
    hist_updates = {}
    if not token or not gid_map:
        return out
    for hn, g in gid_map.items():
        try:
            r = _csqaq_get('/api/v1/info/good/statistic?id=%d' % g, token)
            d = r.get('data') or []
            vals = [x.get('statistic') for x in d if isinstance(x.get('statistic'), int)]
            if not vals:
                continue
            row = {'n_supply_real': int(vals[-1])}
            if len(vals) > 7:
                row['supply_chg7'] = int(vals[-1] - vals[-8])
            out[hn] = row
            hist_updates[hn] = {str(x.get('created_at') or '')[:10]: x.get('statistic')
                                for x in d if isinstance(x.get('statistic'), int)}
        except Exception as e:
            if verbose:
                print('[BUY] 存世量 %s 失败: %s' % (hn[:22], str(e)[:60]), file=sys.stderr)
        _pace_sleep()
    _save_supply_history(hist_updates)
    if verbose:
        print('[BUY] 存世量通道: %d/%d 件' % (len(out), len(gid_map)))
    return out


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
        if bp.get('buff_sell'):
            row['_steamdt_buff'] = float(bp['buff_sell'])   # 跨源留痕（SteamDT 自家值）
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

    out, _gid_map = _csqaq_buy(names, token, verbose)

    # 顺带取真实存世量（复用同一次 goodId 映射，避免重复请求）
    try:
        sup = _csqaq_supply(_gid_map, token, verbose)
        for _hn, _row in sup.items():
            out.setdefault(_hn, {}).update(_row)
    except Exception as _se:
        if verbose:
            print('[BUY] 存世量通道异常: %s' % str(_se)[:100], file=sys.stderr)

    # 交给 SteamDT 的条件：缺买盘，或缺跨平台比价数据（后者原先靠全池 1400 件扫描，成本高）
    missing = [n for n in names
               if not out.get(n) or not out[n].get('buff_buy_num')
               or not out[n].get('platforms')]
    if missing:
        # ⚠ 逐键合并（勿用 out.update(整条替换)）：否则会把先前合并进来的存世量等字段冲掉
        for _hn, _row in (_steamdt_fallback(missing, verbose) or {}).items():
            _keep_src = (out.get(_hn) or {}).get('buy_src')
            out.setdefault(_hn, {}).update(_row)
            # 溯源叠加：两个通道都拿到过买盘时标记为「csqaq_chart+steamdt」，避免被覆盖失真
            if _keep_src and _keep_src != _row.get('buy_src'):
                out[_hn]['buy_src'] = _keep_src + '+' + str(_row.get('buy_src'))

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
