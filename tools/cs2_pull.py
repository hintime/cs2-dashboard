#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从服务器把看板数据拉回本机（异地备份 / 灾难恢复）。

背景
----
2026-09-20 调度上云后，**活跃数据产生在服务器上**，原来的
`cs2_backup.py`（方向：本机 → 服务器）已经不再覆盖活跃数据。
本脚本是反方向：**服务器 → 本机镜像**。

拉什么 / 怎么拉
---------------
    market_history/  339M  增量（865 文件，实测每天只变 3 个）
    index_history/   692K  增量
    顶层 *.json       62M  增量（内容常变，基本全传）
    price_history.db 411M  **每次全量**（sqlite 无简单增量方案）
                           → 远端先做一致性 backup 再 gzip（压缩率约 25%）

落到哪
------
    C:\\Users\\Lenovo\\cs2-mirror\\        ← 独立镜像目录（拉取落这里）

落地（根治脱节）
--------------
    拉完镜像库后，自动把它复制到本地**消费库**（与 price_db.DB_PATH 一致），
    这样 Kronos / 本地看板就能直接吃到最新数据。笔记本纯消费，不回推服务器。
    落地前做 PRAGMA integrity_check + MAX(ts) 比对，旧消费库自动备份为 .prev。

用法
----
    python tools/cs2_pull.py              # 增量拉取 + 自动落地
    python tools/cs2_pull.py --check      # 只看差异，不下载
    python tools/cs2_pull.py --full       # 忽略清单，强制全量
    python tools/cs2_pull.py --no-land    # 只拉镜像，不复制到消费库
    python tools/cs2_pull.py --land-only  # 只把已有镜像库落地（不再拉取）
"""

import os
import sys
import json
import time
import hashlib
import subprocess
import shutil
# 允许 import 仓库根模块（如 price_db）以复用 DB_PATH 解析
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 禁止子进程弹出控制台窗口 ──
# 本脚本由 HKCU\Run 的 pythonw 开机自启（项名 CS2MirrorPull）。pythonw **没有**控制台，
# 于是 ssh/scp/tar/gzip 这些"控制台程序"被拉起来时，Windows 会给每个各新建一个黑色窗口
# 弹到用户面前（2026-10-07 用户反馈「别弹这个窗口了」）。
# 就地包装 subprocess.run 统一补 CREATE_NO_WINDOW —— 一处生效，无需逐处修改。
if os.name == 'nt':
    _SP_RUN_ORIG = subprocess.run

    def _sp_run_nowin(*a, **kw):
        kw.setdefault('creationflags', 0x08000000)   # CREATE_NO_WINDOW
        return _SP_RUN_ORIG(*a, **kw)

    subprocess.run = _sp_run_nowin

SSH = r"C:\Windows\System32\OpenSSH\ssh.exe"
SCP = r"C:\Windows\System32\OpenSSH\scp.exe"
KEY = os.path.join(os.path.expanduser("~"), ".ssh", "cs.pem")
HOST = "ubuntu@82.156.128.138"
RUN = "/home/ubuntu/cs2-run"

MIRROR = r"E:\cs2-mirror"
MANIFEST = os.path.join(MIRROR, "_manifest.json")
LOGFILE = os.path.join(MIRROR, "_pull.log")
AUTO_MIN_HOURS = 20      # --auto 模式下，距上次拉取不足此小时数就跳过

# 要镜像的路径（相对 RUN）
INCLUDE_DIRS = ["market_history", "index_history"]
INCLUDE_TOP = True          # 顶层 *.json
DB_NAME = "price_history.db"

# 落地目标：本地消费库（与 price_db.DB_PATH 一致）。拉取完成后自动把镜像库复制到这里，
# 根治「拉到了但本地仍是旧数据」的脱节。笔记本纯消费，不回推服务器。
try:
    import price_db
    LAND_PATH = price_db.DB_PATH
except Exception:
    LAND_PATH = r"E:\cs2-data\price_history.db"


def _db_tables(db_path):
    import sqlite3
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    con.close()
    return tables


def _max_ts(db_path):
    """取价格表的最大 ts（ISO 字符串，按字典序可比）。"""
    import sqlite3
    tables = _db_tables(db_path)
    if not tables:
        return None
    table = "prices" if "prices" in tables else tables[0]
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute('SELECT MAX(ts) FROM "%s"' % table)
    mx = cur.fetchone()[0]
    con.close()
    return mx


def land_db():
    """把镜像库复制到本地消费库（price_db.DB_PATH），根治「拉到了但本地仍是旧数据」。

    落地前做：PRAGMA integrity_check 完整性 + MAX(ts) 比对（不比旧值新就跳过），
    落地时把旧消费库备份为 .prev，失败不影响已存在的消费库。
    返回 True 表示落地成功或本就最新（无需动作），False 表示中止/失败。
    """
    src = os.path.join(MIRROR, DB_NAME)
    if not os.path.exists(src):
        log("落地中止：镜像库不存在 %s（先跑一次普通拉取）" % src)
        return False

    # 1) 先做便宜的 MAX(ts) 比对（走 ts 索引，O(1)）：不比旧值新就直接跳过，
    #    避免每次都跑全库 integrity_check（1.4GB 约 3 分钟）。
    new_max = _max_ts(src)
    old_max = _max_ts(LAND_PATH) if os.path.exists(LAND_PATH) else None
    if old_max is not None and new_max is not None and str(new_max) <= str(old_max):
        log("落地跳过：镜像库 MAX(ts)=%s 不比本地 %s 新" % (new_max, old_max))
        return True

    # 2) 确实需要落地：做完整性校验（gzip 自带 CRC，但磁盘/文件系统可能静默损坏）
    try:
        import sqlite3
        con = sqlite3.connect(src)
        cur = con.cursor()
        cur.execute("PRAGMA integrity_check(1)")
        row = cur.fetchone()
        con.close()
        if not row or row[0] != "ok":
            log("落地中止：镜像库完整性校验失败 %r" % (row,))
            return False
    except Exception as e:
        log("落地中止：镜像库读取失败 %s" % e)
        return False

    # 3) 备份旧消费库 → 复制新库
    try:
        if os.path.exists(LAND_PATH):
            backup = LAND_PATH + ".prev"
            if os.path.exists(backup):
                os.remove(backup)
            os.replace(LAND_PATH, backup)
        shutil.copy2(src, LAND_PATH)
        log("落地完成：%s → %s  (MAX(ts): %s → %s, %.1f MB)"
            % (src, LAND_PATH, old_max, new_max,
               os.path.getsize(LAND_PATH) / 1024 / 1024))
        return True
    except Exception as e:
        log("落地失败：%s" % e)
        return False


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(MIRROR, exist_ok=True)
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def sh(cmd, timeout=1800, binary=False):
    p = subprocess.run([SSH, "-i", KEY, "-o", "BatchMode=yes",
                        "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
                        HOST, cmd],
                       capture_output=True, timeout=timeout)
    if binary:
        return p.returncode, p.stdout
    return (p.returncode,
            (p.stdout or b"").decode("utf-8", "replace"),
            (p.stderr or b"").decode("utf-8", "replace"))


def _ssh_in(local_path, remote_path, timeout=300):
    """用 ssh stdin 管道把本地文件推到远端（替代 scp 上传，scb 在本沙箱坏）。"""
    with open(local_path, "rb") as f:
        data = f.read()
    p = subprocess.run([SSH, "-i", KEY, "-o", "BatchMode=yes",
                        "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
                        HOST, "cat > " + remote_path],
                       input=data, capture_output=True, timeout=timeout)
    return p.returncode, (p.stderr or b"").decode("utf-8", "replace")


def _ssh_out(remote_path, local_path, timeout=7200, expected_size=None):
    """用 ssh stdout 管道把远端文件拉到本地（替代 scp 下载，二进制安全）。

    数据流：远端 cat → ssh 加密通道 → 本机内存 → 直接以字节写盘，不经过
    任何文本模式转换，避免 CRLF 污染。gzip 自带 CRC，解压失败即能发现损坏。
    """
    p = subprocess.run([SSH, "-i", KEY, "-o", "BatchMode=yes",
                        "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
                        HOST, "cat " + remote_path],
                       capture_output=True, timeout=timeout)
    if p.returncode != 0:
        return p.returncode, (p.stderr or b"").decode("utf-8", "replace")
    with open(local_path, "wb") as f:
        f.write(p.stdout)
    if expected_size is not None and os.path.getsize(local_path) != expected_size:
        return 2, "size mismatch: got %d want %d" % (os.path.getsize(local_path), expected_size)
    return 0, ""


def remote_manifest():
    """远端生成清单：每行 relpath\\tsize\\tmtime"""
    inc = " ".join(INCLUDE_DIRS)
    cmd = ("cd %s && { find %s -type f 2>/dev/null; ls *.json 2>/dev/null; } "
           "| while read f; do printf '%%s\\t%%s\\t%%s\\n' \"$f\" "
           "\"$(stat -c %%s \"$f\")\" \"$(stat -c %%Y \"$f\")\"; done" % (RUN, inc))
    rc, out, err = sh(cmd, timeout=600)
    if rc != 0:
        raise RuntimeError("远端清单生成失败: %s" % err[:200])
    m = {}
    for line in out.split("\n"):
        parts = line.strip().split("\t")
        if len(parts) == 3:
            m[parts[0]] = (int(parts[1]), float(parts[2]))
    return m


def main():
    check_only = "--check" in sys.argv
    force_full = "--full" in sys.argv
    auto = "--auto" in sys.argv
    land_only = "--land-only" in sys.argv
    no_land = "--no-land" in sys.argv
    t0 = time.time()

    # --land-only：不重新拉取，只把已有的镜像库落地（幂等重跑用）
    if land_only:
        log("=" * 56)
        log("--land-only：跳过远端拉取，仅执行落地")
        ok = land_db()
        log("落地结束（%s），总用时 %.0fs" % ("OK" if ok else "FAIL", time.time() - t0))
        return 0 if ok else 1

    os.makedirs(MIRROR, exist_ok=True)

    # --auto：供开机自启调用。距上次成功拉取不足 AUTO_MIN_HOURS 小时就跳过，
    # 免得每次开机都拉一遍 130MB。本机不进常驻进程，只在登录时跑一次。
    if auto and os.path.exists(MANIFEST):
        age_h = (time.time() - os.path.getmtime(MANIFEST)) / 3600.0
        if age_h < AUTO_MIN_HOURS:
            log("--auto: 距上次拉取 %.1f 小时（<%.0fh），跳过" % (age_h, AUTO_MIN_HOURS))
            return 0
        log("--auto: 距上次拉取 %.1f 小时，开始增量拉取" % age_h)

    prev = {}
    if not force_full and os.path.exists(MANIFEST):
        try:
            prev = json.load(open(MANIFEST, encoding="utf-8"))
        except Exception:
            prev = {}

    log("=" * 56)
    log("拉取开始（%s）" % ("全量" if force_full else "增量"))

    # ── 1. 差异比对 ──
    log("读取远端清单 ...")
    cur = remote_manifest()
    log("  远端文件数: %d" % len(cur))
    # 差异 = 新增 / size 变 / mtime 变
    changed = []
    for k, v in cur.items():
        pv = prev.get(k)
        if force_full or pv is None or tuple(pv) != tuple(v):
            changed.append(k)
    log("  需要更新的文件: %d 个（共 %.1f MB）"
        % (len(changed), sum(cur[k][0] for k in changed) / 1024 / 1024))

    if check_only:
        for k in changed[:25]:
            log("    %s  %.1f KB" % (k, cur[k][0] / 1024))
        if len(changed) > 25:
            log("    ... 还有 %d 个" % (len(changed) - 25))
        log("(--check 模式，未下载)")
        return 0

    # ── 2. 增量文件打包 ──
    if changed:
        lst = os.path.join(MIRROR, "_pull_list.txt")
        with open(lst, "w", encoding="utf-8", newline="\n") as f:
            for k in changed:
                f.write("./" + k + "\n")
        log("上传清单到远端（ssh 管道）...")
        rc, err = _ssh_in(lst, "/tmp/_pull_list.txt")
        if rc != 0:
            log("  清单上传失败: %s" % err[:200])
            return 1
        log("远端打包增量 ...")
        rc, out, err = sh("cd %s && tar -czf /tmp/_pull.tar.gz -T /tmp/_pull_list.txt "
                          "2>/dev/null; ls -l /tmp/_pull.tar.gz | awk '{print $5}'" % RUN,
                          timeout=1800)
        size = (out or "").strip().split("\n")[-1]
        log("  打包完成: %s bytes" % size)

        arc = os.path.join(MIRROR, "_pull.tar.gz")
        log("下载增量包（ssh 管道）...")
        rc, err = _ssh_out("/tmp/_pull.tar.gz", arc)
        if rc != 0:
            log("  下载失败: %s" % err[:200])
            return 1
        log("  下载完成 %.1f MB，解压 ..." % (os.path.getsize(arc) / 1024 / 1024))
        r = subprocess.run(["tar", "xzf", arc, "-C", MIRROR], capture_output=True)
        if r.returncode != 0:
            log("  解压失败: %s" % (r.stderr or b"").decode("utf-8", "replace")[:200])
            return 1
        os.remove(arc)
        sh("rm -f /tmp/_pull.tar.gz /tmp/_pull_list.txt", timeout=120)
    else:
        log("  无变化，跳过文件下载")

    # ── 3. db（每次都拉，用一致性快照 + gzip）──
    log("db 一致性快照（远端 sqlite backup + gzip）...")
    rc, out, err = sh(
        "cd %s && /home/ubuntu/cs2-run/venv/bin/python -c \""
        "import sqlite3;"
        "s=sqlite3.connect('price_history.db');d=sqlite3.connect('/tmp/_ph.db');"
        "s.backup(d);d.close();s.close()\" && gzip -1 -f /tmp/_ph.db && "
        "ls -l /tmp/_ph.db.gz | awk '{print $5}'" % RUN, timeout=1800)
    dbsize = (out or "").strip().split("\n")[-1]
    log("  快照完成: %s bytes" % dbsize)

    dbarc = os.path.join(MIRROR, "_ph.db.gz")
    log("下载 db 快照（ssh 管道）...")
    t1 = time.time()
    rc, err = _ssh_out("/tmp/_ph.db.gz", dbarc, expected_size=(int(dbsize) if dbsize.isdigit() else None))
    if rc != 0:
        log("  db 下载失败: %s" % err[:200])
        return 1
    dt = time.time() - t1
    mb = os.path.getsize(dbarc) / 1024 / 1024
    log("  下载完成 %.1f MB，用时 %.0fs (%.2f MB/s)" % (mb, dt, mb / max(dt, 1)))

    log("解压 db 到镜像 ...")
    r = subprocess.run(["gzip", "-d", "-f", dbarc], capture_output=True)
    tmpdb = os.path.join(MIRROR, "_ph.db")
    if r.returncode != 0 or not os.path.exists(tmpdb):
        log("  解压失败（gzip 不可用？）: %s" % (r.stderr or b"").decode("utf-8", "replace")[:150])
        log("  保留 .gz 原文于 %s" % dbarc)
    else:
        dst = os.path.join(MIRROR, DB_NAME)
        try:
            if os.path.exists(dst):
                os.replace(dst, dst + ".prev")
            os.replace(tmpdb, dst)
            log("  db 已更新: %s (%.1f MB)" % (dst, os.path.getsize(dst) / 1024 / 1024))
        except Exception as e:
            log("  替换失败: %s" % e)
    sh("rm -f /tmp/_ph.db.gz", timeout=120)

    # ── 4. 保存清单 ──
    cur2 = remote_manifest()
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(cur2, f, ensure_ascii=False)
    log("清单已保存（%d 条）" % len(cur2))

    # ── 5. 落地（复制镜像库到本地消费库）──
    if no_land:
        log("（--no-land：跳过落地）")
    else:
        land_db()

    log("拉取结束，总用时 %.0fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
