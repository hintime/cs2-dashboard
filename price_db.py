#!/usr/bin/env python3
"""SQLite 全量价格历史存储 — 替代 price_history.json 的 JSON 方案
- 所有 ECO 扫描物品的价格都记录（不再受限 BUFF/YY 门槛）
- 三通道：eco / buff / yy
- 原子写入，防截断
- 提供生成 price_summary.json 的方法
"""
import sqlite3, json, os, time, sys

# 价格历史库默认迁到 E 盘（C 盘空间紧张；362MB+ 且只增不减）。
# 可用环境变量 PRICE_HIST_DB 覆盖（如仍想留在仓库内则设回仓库路径）。
# 2026-09-18 迁移：原 C:\Users\Lenovo\cs2-runner-local\price_history.db
#   → E:\cs2-data\price_history.db（sqlite 在线 backup，行数一致校验通过）。
#
# ⚠ 2026-09-20 修：原来无论什么平台都拼 `E:\cs2-data`，**在 Linux 上会新建一个
#   名为 `E:\cs2-data` 的字面量目录**（因为 'E:' 在 Linux 只是普通字符），
#   然后得到一个空库 → 查询全空、还留下垃圾目录。
#   现在按平台分流：Windows 用 E 盘，其他平台落在本文件所在目录。
if os.environ.get('PRICE_HIST_DB'):
    DB_PATH = os.environ['PRICE_HIST_DB']
elif sys.platform == 'win32':
    DB_PATH = os.path.join('E:\\cs2-data', 'price_history.db')
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'price_history.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def _now():
    return time.strftime('%Y-%m-%dT%H:%M', time.gmtime())

def get_db():
    """获取数据库连接（自动初始化表结构）"""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    # ⚠ 2026-09-20 加：history 频率提到 1h 后，会与 `all`（0 分启动、约 78 分钟）
    #   在同一时段写库。WAL 允许并发读，但**写是串行的** —— 没有 busy_timeout 时
    #   第二个写会立刻抛 `database is locked`，直接丢掉这一轮采样。
    #   30 秒足够等前一个批量插入完成。
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA cache_size=-8000')  # 8MB cache
    conn.execute('''CREATE TABLE IF NOT EXISTS prices (
        item_name TEXT NOT NULL,
        channel  TEXT NOT NULL,
        ts       TEXT NOT NULL,
        price    REAL NOT NULL,
        PRIMARY KEY (item_name, channel, ts)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_lookup ON prices(item_name, channel, ts)')
    conn.execute('''CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    # ★ 2026-09-21：盘口量历史表（在售/求购）。
    #   prices 只存价格，算不出「在售异动 / 求购异动」；本表从今日起积累。
    conn.execute('''CREATE TABLE IF NOT EXISTS boards (
        item_name     TEXT NOT NULL,
        ts            TEXT NOT NULL,
        buff_sell_num INTEGER DEFAULT 0,
        buff_buy_num  INTEGER DEFAULT 0,
        eco_selling   INTEGER DEFAULT 0,
        eco_qg        INTEGER DEFAULT 0,
        PRIMARY KEY (item_name, ts)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_boards ON boards(item_name, ts)')
    return conn

# ═══════════════ 写入 ═══════════════

def record(item_name, channel, ts, price):
    """记录单个数据点 (INSERT OR IGNORE 避免重复)"""
    conn = get_db()
    try:
        conn.execute(
            'INSERT OR IGNORE INTO prices(item_name, channel, ts, price) VALUES (?,?,?,?)',
            (item_name, channel, ts, price)
        )
        conn.commit()
    finally:
        conn.close()

def record_batch(records):
    """批量记录：[(item_name, channel, ts, price), ...]"""
    if not records:
        return 0
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.executemany(
            'INSERT OR IGNORE INTO prices(item_name, channel, ts, price) VALUES (?,?,?,?)',
            records
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()

def import_from_price_history_json(ph_file):
    """从旧 price_history.json 迁移数据到 SQLite"""
    if not os.path.exists(ph_file):
        print(f'[DB-MIGRATE] {ph_file} not found, skip')
        return 0
    try:
        with open(ph_file, 'r', encoding='utf-8') as f:
            ph = json.load(f)
    except Exception as e:
        print(f'[DB-MIGRATE] Failed to read {ph_file}: {e}')
        return 0

    records = []
    for item_name, sources in ph.items():
        if not isinstance(sources, dict):
            continue
        for channel in ('eco', 'multi', 'yyyp'):
            pts = sources.get(channel, [])
            if not pts:
                continue
            ch_name = {'eco': 'eco', 'multi': 'buff', 'yyyp': 'yy'}.get(channel, channel)
            for dp in pts:
                if isinstance(dp, dict):
                    records.append((item_name, ch_name, dp.get('t', ''), dp.get('p', 0)))

    count = record_batch(records)
    print(f'[DB-MIGRATE] Imported {count} records from price_history.json ({len(records)} attempted)')
    return count

def import_from_buff_history(bh_file):
    """从 buff_history.json 迁移 BUFF 数据到 SQLite"""
    if not os.path.exists(bh_file):
        print(f'[DB-MIGRATE] {bh_file} not found, skip')
        return 0
    try:
        with open(bh_file, 'r', encoding='utf-8') as f:
            bh = json.load(f)
    except Exception as e:
        print(f'[DB-MIGRATE] Failed to read {bh_file}: {e}')
        return 0

    records = []
    for date_key, items in bh.items():
        if not isinstance(items, dict):
            continue
        # date_key format: "2026-06-14" or "2026-06-14T20:00"
        for item_name, info in items.items():
            if not isinstance(info, dict):
                # legacy: direct price number
                try:
                    p = float(info)
                    if p > 0:
                        records.append((item_name, 'buff', date_key, p))
                except (ValueError, TypeError):
                    pass
                continue
            # current format: {'buff_sell': xxx, 'yyyp_sell': xxx, ...}
            for field, channel in [('buff_sell', 'buff'), ('yyyp_sell', 'yy')]:
                try:
                    p = float(info.get(field, 0))
                    if p > 0:
                        records.append((item_name, channel, date_key, p))
                except (ValueError, TypeError):
                    pass

    count = record_batch(records)
    print(f'[DB-MIGRATE] Imported {count} records from buff_history.json ({len(records)} attempted)')
    return count

# ═══════════════ 查询 ═══════════════

def get_history(item_name, channel=None, start_ts=None, end_ts=None):
    """查询指定物品的价格历史"""
    conn = get_db()
    try:
        sql = 'SELECT channel, ts, price FROM prices WHERE item_name = ?'
        params = [item_name]
        if channel:
            sql += ' AND channel = ?'
            params.append(channel)
        if start_ts:
            sql += ' AND ts >= ?'
            params.append(start_ts)
        if end_ts:
            sql += ' AND ts <= ?'
            params.append(end_ts)
        sql += ' ORDER BY ts ASC'
        rows = conn.execute(sql, params).fetchall()
        return [{'channel': r[0], 'ts': r[1], 'price': r[2]} for r in rows]
    finally:
        conn.close()

def get_daily_averages(item_name, channel='eco', days=30):
    """获取日平均价列表，用于前端图表"""
    conn = get_db()
    try:
        cutoff = time.time() - days * 86400
        cutoff_ts = time.strftime('%Y-%m-%d', time.gmtime(cutoff))
        rows = conn.execute(
            'SELECT date(ts) as day, AVG(price) as avg_p, MIN(price), MAX(price), COUNT(*) '
            'FROM prices WHERE item_name=? AND channel=? AND ts >= ? '
            'GROUP BY day ORDER BY day',
            (item_name, channel, cutoff_ts)
        ).fetchall()
        return [{'day': r[0], 'avg': round(r[1], 2), 'min': round(r[2], 2), 'max': round(r[3], 2), 'n': r[4]} for r in rows]
    finally:
        conn.close()

def get_price_change(item_name, channel='eco', days=7):
    """计算 N 日涨跌幅"""
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT AVG(price) FROM prices WHERE item_name=? AND channel=? AND ts >= date("now", ?)',
            (item_name, channel, f'-{days} days')
        ).fetchone()
        if not rows or rows[0] is None:
            return 0
        return round(rows[0], 2)
    finally:
        conn.close()

# ═══════════════ 统计 ═══════════════

def get_stats():
    """数据库概览统计"""
    conn = get_db()
    try:
        total = conn.execute('SELECT COUNT(*) FROM prices').fetchone()[0]
        items = conn.execute('SELECT COUNT(DISTINCT item_name) FROM prices').fetchone()[0]
        channels = conn.execute(
            'SELECT channel, COUNT(*) as cnt, COUNT(DISTINCT item_name) as items '
            'FROM prices GROUP BY channel'
        ).fetchall()
        ts_range = conn.execute(
            'SELECT MIN(ts), MAX(ts) FROM prices'
        ).fetchone()

        result = {
            'total_records': total,
            'total_items': items,
            'channels': {r[0]: {'records': r[1], 'items': r[2]} for r in channels},
            'first_ts': ts_range[0],
            'last_ts': ts_range[1],
            'db_size_mb': round(os.path.getsize(DB_PATH) / 1024 / 1024, 2) if os.path.exists(DB_PATH) else 0
        }
        return result
    finally:
        conn.close()

# ═══════════════ 数据保持 ═══════════════

def trim_old_data(max_days=90, vacuum_min_rows=200000):
    """清理超过 max_days 天的数据。

    ⚠ 2026-09-20 修：原来只要删了**任意一条**就 `VACUUM`。而本函数在 history 模式里
    **每次落库后都会调用**；history 提到 1h 后，一旦 db 越过保留期，就会变成
    **每小时 VACUUM 一次整个库** —— 那是几分钟的阻塞 + 需要近等量的临时磁盘空间
    （db 到 5GB 时就是 5GB 临时空间），会直接把服务器拖垮。

    改法：只有删除量足够大（默认 20 万行）才 VACUUM。日常少量删除**不需要**回收 ——
    SQLite 会把删掉的页标为空闲、后续插入直接复用，db 体积会稳定在保留期对应的大小。
    """
    conn = get_db()
    try:
        cutoff = time.strftime('%Y-%m-%d', time.gmtime(time.time() - max_days * 86400))
        deleted = conn.execute('DELETE FROM prices WHERE date(ts) < ?', (cutoff,)).rowcount
        conn.commit()
        if deleted >= vacuum_min_rows:
            print(f'[DB-TRIM] Deleted {deleted:,} records older than {max_days} days '
                  f'-> VACUUM（删除量大，回收空间）')
            conn.execute('VACUUM')
        elif deleted:
            print(f'[DB-TRIM] Deleted {deleted:,} records older than {max_days} days '
                  f'（量小，跳过 VACUUM，空闲页会被后续插入复用）')
        return deleted
    finally:
        conn.close()

# ═══════════════ 前端摘要生成 ═══════════════

def generate_price_summary(output_path='price_summary.json'):
    """从 SQLite 生成 price_summary.json（前端图表用）
    优先级：BUFF > YY > ECO（按物品覆盖率选最优通道）
    """
    conn = get_db()
    try:
        # 获取所有物品（跨所有通道）
        all_items = [r[0] for r in conn.execute(
            'SELECT DISTINCT item_name FROM prices'
        ).fetchall()]

        summary = {}

        for item_name in all_items:
            # 按优先级尝试各通道：BUFF(最全) → YY → ECO
            best_channel = None
            best_daily = []

            for ch in ('buff', 'yy', 'eco'):
                daily = conn.execute(
                    'SELECT date(ts) as day, ROUND(AVG(price), 2) '
                    'FROM prices WHERE item_name=? AND channel=? '
                    'AND ts >= date("now", "-30 days") '
                    'GROUP BY day ORDER BY day',
                    (item_name, ch)
                ).fetchall()

                if daily and len(daily) >= 2:  # 至少 2 天数据才有意义
                    best_channel = ch
                    best_daily = daily
                    break
                elif daily and not best_daily:
                    # 作为兜底（哪怕只有1天）
                    best_channel = ch
                    best_daily = daily

            if not best_daily:
                continue

            days_list = [d[0] for d in best_daily]
            prices_list = [d[1] for d in best_daily]

            if len(prices_list) >= 2:
                mid = max(0, len(prices_list) - 8)
                old_7 = prices_list[mid]
                new_7 = prices_list[-1]
                chg_7 = round((new_7 - old_7) / old_7 * 100, 1) if old_7 > 0 else 0

                old_30 = prices_list[0]
                new_30 = prices_list[-1]
                chg_30 = round((new_30 - old_30) / old_30 * 100, 1) if old_30 > 0 else 0
            else:
                chg_7 = chg_30 = 0

            summary[item_name] = {
                'days': days_list[-30:],
                'prices': prices_list[-30:],
                'change_7d': chg_7,
                'change_30d': chg_30,
                'channel': best_channel,  # 标记数据来源
            }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False)
        print(f'[DB-SUMMARY] Generated {output_path}: {len(summary)} items')
        return summary
    finally:
        conn.close()

def record_boards_batch(records):
    """批量记录盘口量：[(item_name, ts, buff_sell_num, buff_buy_num, eco_selling, eco_qg), ...]

    ★ 2026-09-21：price_history 只存价格，算不出「在售异动 / 求购异动」，
    盘口量单独建表，从本日起积累。
    """
    if not records:
        return 0
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.executemany(
            'INSERT OR IGNORE INTO boards'
            '(item_name, ts, buff_sell_num, buff_buy_num, eco_selling, eco_qg)'
            ' VALUES (?,?,?,?,?,?)', records)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_board_movers(steps=1, limit=8, min_base=3):
    """盘口**即时**异动：相邻 steps 个采样点之间的变化（steps=1 → 本次 vs 上次）。

    ★ 2026-09-21 义轩要求：异动要「即时」，不要与 24 小时比 ——
      扫货 / 抛售 / 求购暴增这类事件当天就发生，24 小时窗口会把它稀释掉。

    返回 {'sell': {'add': [...], 'drop': [...]},
          'buy':  {'add': [...], 'drop': [...]},
          'base_ts': 最新采样, 'prev_ts': 对比采样, 'points': 采样点数, 'total': 标的数}
    每项 {'name','old','new','diff','pct'}。
    在售口径 = BUFF 在售数，求购口径 = BUFF 求购数（都从 eco_tracked.json 零成本取得）。
    """
    import collections
    out = {'sell': {'add': [], 'drop': []}, 'buy': {'add': [], 'drop': []},
           'base_ts': None, 'prev_ts': None, 'points': 0, 'total': 0}
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT item_name, ts, buff_sell_num, buff_buy_num'
            ' FROM boards ORDER BY ts').fetchall()
    finally:
        conn.close()
    if not rows:
        return out

    series = collections.defaultdict(list)
    for nm, ts, bs, bb in rows:
        series[nm].append((ts, bs or 0, bb or 0))

    tss = sorted({r[1] for r in rows})
    out['points'] = len(tss)
    out['total'] = len(series)
    out['base_ts'] = tss[-1]
    if len(tss) <= steps:
        return out                      # 采样点不够，无从对比
    out['prev_ts'] = tss[-1 - steps]

    def _delta(idx):
        res = []
        for nm, lst in series.items():
            if len(lst) <= steps:
                continue
            cur = lst[-1][1:][idx]
            prev = lst[-1 - steps][1:][idx]
            if prev < min_base:         # 基数太小的百分比噪声大
                continue
            d = cur - prev
            if d == 0:
                continue
            res.append({'name': nm, 'old': prev, 'new': cur, 'diff': d,
                        'pct': round(d / prev * 100, 1) if prev else 0.0})
        return res

    sell = _delta(0)
    buy = _delta(1)
    out.update(
        sell={'add': sorted([x for x in sell if x['diff'] > 0],
                            key=lambda x: -x['diff'])[:limit],
              'drop': sorted([x for x in sell if x['diff'] < 0],
                             key=lambda x: x['diff'])[:limit]},
        buy={'add': sorted([x for x in buy if x['diff'] > 0],
                           key=lambda x: -x['diff'])[:limit],
             'drop': sorted([x for x in buy if x['diff'] < 0],
                            key=lambda x: x['diff'])[:limit]})
    return out
def get_movers_data():
    """为 generate_scan.py 提供涨跌榜所需数据"""
    conn = get_db()
    try:
        # 获取每个物品最近的 ECO 价格和 24h 前的价格
        rows = conn.execute('''
            SELECT item_name, ts, price FROM prices
            WHERE channel='eco' AND item_name IN (
                SELECT DISTINCT item_name FROM prices WHERE channel='eco'
                GROUP BY item_name HAVING COUNT(*) >= 3
            )
            ORDER BY item_name, ts
        ''').fetchall()

        # 按物品分组
        from collections import defaultdict
        history = defaultdict(list)
        for name, ts, price in rows:
            history[name].append({'t': ts, 'p': price})

        return dict(history)
    finally:
        conn.close()

def get_raw_history():
    """返回旧 price_history.json 格式的全量数据
    {item_name: {eco: [{t, p}, ...], buff: [...], yy: [...]}}
    供 generate_correlation.py 等下游使用
    """
    conn = get_db()
    try:
        from collections import defaultdict
        result = defaultdict(lambda: {'eco': [], 'buff': [], 'yy': []})
        rows = conn.execute(
            'SELECT item_name, channel, ts, price FROM prices ORDER BY ts'
        ).fetchall()
        for name, ch, ts, price in rows:
            if ch not in ('eco', 'buff', 'yy'):
                continue
            result[name][ch].append({'t': ts, 'p': price})
        return dict(result)
    finally:
        conn.close()


# ═══════════════ CLI ═══════════════

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stats'

    if cmd == 'init':
        get_db()
        print(f'[DB] Initialized: {DB_PATH}')

    elif cmd == 'migrate':
        n1 = import_from_price_history_json('price_history.json')
        n2 = import_from_buff_history('buff_history.json')
        print(f'[DB] Migration done: {n1} from price_history.json, {n2} from buff_history.json')

    elif cmd == 'stats':
        stats = get_stats()
        print(f'[DB] Stats:')
        print(f'  Records: {stats["total_records"]:,}')
        print(f'  Items:   {stats["total_items"]:,}')
        print(f'  Size:    {stats["db_size_mb"]} MB')
        print(f'  Range:   {stats["first_ts"]} ~ {stats["last_ts"]}')
        for ch, info in stats['channels'].items():
            print(f'  {ch}: {info["records"]:,} records, {info["items"]:,} items')

    elif cmd == 'summary':
        generate_price_summary()

    elif cmd == 'trim':
        trim_old_data()

    else:
        print(f'Usage: python price_db.py [init|migrate|stats|summary|trim]')
