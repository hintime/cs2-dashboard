#!/usr/bin/env python3
"""SQLite 全量价格历史存储 — 替代 price_history.json 的 JSON 方案
- 所有 ECO 扫描物品的价格都记录（不再受限 BUFF/YY 门槛）
- 三通道：eco / buff / yy
- 原子写入，防截断
- 提供生成 price_summary.json 的方法
"""
import sqlite3, json, os, time, sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'price_history.db')

def _now():
    return time.strftime('%Y-%m-%dT%H:%M', time.gmtime())

def get_db():
    """获取数据库连接（自动初始化表结构）"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
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

def trim_old_data(max_days=90):
    """清理超过 max_days 天的数据（保持 DB 可控大小）"""
    conn = get_db()
    try:
        cutoff = time.strftime('%Y-%m-%d', time.gmtime(time.time() - max_days * 86400))
        deleted = conn.execute('DELETE FROM prices WHERE date(ts) < ?', (cutoff,)).rowcount
        conn.commit()
        if deleted:
            print(f'[DB-TRIM] Deleted {deleted} records older than {max_days} days')
            conn.execute('VACUUM')
        return deleted
    finally:
        conn.close()

# ═══════════════ 前端摘要生成 ═══════════════

def generate_price_summary(output_path='price_summary.json'):
    """从 SQLite 生成 price_summary.json（前端图表用）"""
    conn = get_db()
    try:
        # 获取所有物品
        items = [r[0] for r in conn.execute(
            'SELECT DISTINCT item_name FROM prices WHERE channel="eco"'
        ).fetchall()]

        summary = {}
        now_ts = time.time()

        for item_name in items:
            # 最近 30 天的日平均价
            daily = conn.execute(
                'SELECT date(ts) as day, ROUND(AVG(price), 2) '
                'FROM prices WHERE item_name=? AND channel="eco" '
                'AND ts >= date("now", "-30 days") '
                'GROUP BY day ORDER BY day',
                (item_name,)
            ).fetchall()

            if not daily:
                continue

            days_list = [d[0] for d in daily]
            prices_list = [d[1] for d in daily]

            if len(prices_list) >= 2:
                # 7日涨跌
                mid = max(0, len(prices_list) - 8)
                old_7 = prices_list[mid]
                new_7 = prices_list[-1]
                chg_7 = round((new_7 - old_7) / old_7 * 100, 1) if old_7 > 0 else 0

                # 30日涨跌
                old_30 = prices_list[0]
                new_30 = prices_list[-1]
                chg_30 = round((new_30 - old_30) / old_30 * 100, 1) if old_30 > 0 else 0
            else:
                chg_7 = chg_30 = 0

            # 只保留日期和均价（精简）
            summary[item_name] = {
                'days': days_list[-30:],
                'prices': prices_list[-30:],
                'change_7d': chg_7,
                'change_30d': chg_30,
            }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False)
        print(f'[DB-SUMMARY] Generated {output_path}: {len(summary)} items')
        return summary
    finally:
        conn.close()

def get_movers_data():
    """为 generate_scan.py 提供涨跌榜所需数据"""
    conn = get_db()
    try:
        # 获取每个物品最近的 ECO 价格和 24h 前的价格
        rows = conn.execute('''
            SELECT item_name, ts, price FROM prices
            WHERE channel='eco' AND item_name IN (
                SELECT DISTINCT item_name FROM prices WHERE channel='eco'
                GROUP BY item_name HAVING COUNT(*) >= 10
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
