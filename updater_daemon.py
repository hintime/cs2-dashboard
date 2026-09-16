#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 看板 · 本机定时更新调度器
================================
替代 GitHub Actions 的 self-hosted runner，彻底摆脱 runner 断连/调度丢失的问题。

设计要点：
  · 直接调用仓库自带的 update.py（它自带 git pull / 抓数据 / commit / push）
  · **关键**：运行时不设置 GITHUB_ACTIONS，update.py 就会走「本地」分支自己推送
  · 两个周期：每 30 分钟 prices（不调 AI）；每 6 小时 all（含 AI 分析）
  · 纯标准库，无第三方依赖；单进程常驻，不弹窗

用法：
    python updater_daemon.py            # 前台运行（调试用）
    python updater_daemon.py --once prices   # 只跑一次 prices
    python updater_daemon.py --once all      # 只跑一次 all
    python updater_daemon.py --status        # 查看状态

日志：logs/updater_YYYY-MM-DD.log
"""
import os
import sys
import time
import json
import subprocess
import argparse
import traceback
from datetime import datetime, timedelta

# ── 强制 stdout/stderr 用 UTF-8 ──
# ⚠️ 2026-09-16 血泪教训（本 bug 让调度器「拉起即死」了 1.5 小时）：
#    由计划任务拉起的进程，stdout 继承系统默认代码页 cp936(GBK)。
#    而下面的日志里用了 "▶"（U+25B6）——**GBK 里没有这个字符** ——
#    于是 print() 抛 UnicodeEncodeError；"─"(U+2500) 恰好在 GBK 里有编码，
#    所以日志总是"打印完分隔线就没了"。
#    更糟的是异常被 main_loop 捕获后试图 log("主循环异常...")，
#    而 traceback 里正好包含那行含 "▶" 的源码 → 二次抛异常 → 直接跳到
#    finally 退出，**连异常原因都留不下来**，排查时完全看不到线索。
#    子进程 update.py 之所以没事，是因为 run_update() 给它传了
#    PYTHONIOENCODING=utf-8；父进程自己漏了。
#    这里补上（errors="replace" 兜底，任何情况下都不再抛）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── git safe.directory ──
# 当本调度器由计划任务以 SYSTEM 运行时，仓库属主是交互用户，
# git >= 2.35.2 会拒绝操作。经环境变量通道注入（同命令行 -c 优先级）。
if not os.environ.get("GIT_CONFIG_COUNT"):
    os.environ["GIT_CONFIG_COUNT"] = "1"
    os.environ["GIT_CONFIG_KEY_0"] = "safe.directory"
    os.environ["GIT_CONFIG_VALUE_0"] = "*"

# ── 路径 ──
# 调度器会按顺序寻找第一个「可用的完整仓库」作为运行目录：
#   1. 脚本所在目录（若已含 update.py）
#   2. 环境变量 CS2_REPO 指定的目录
#   3. 已知候选目录（本机各克隆）
HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(HERE, "logs")
LOCKFILE = os.path.join(HERE, ".updater.lock")
STATEFILE = os.path.join(HERE, ".updater_state.json")

_TOKEN_SRC = None

# 必须在 `_git_ok` / `find_repo` 之前定义 —— 它们会在模块加载期被调用，
# 若放到后面会触发 NameError（被 except 吞掉 → 所有候选仓库被判为不可用
# → 静默回退到 HERE，选错仓库）。
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _local_github_token():
    """取本机可用的 GitHub token，供 update.py 的本地 push 使用。

    顺序：
      1. 环境变量 GH_TOKEN / GH_PAT
      2. 仓库内 local_keys.env（不入 git）
      3. Windows 凭据管理器（target = git:https://github.com）

    第 3 条用 CredReadW（advapi32）直读：`git credential fill` 在无交互
    环境里会报 "Cannot prompt because user interactivity has been disabled"。
    """
    global _TOKEN_SRC
    for k in ("GH_TOKEN", "GH_PAT", "GITHUB_TOKEN"):
        v = os.environ.get(k)
        if v:
            _TOKEN_SRC = "env"
            return v

    # 2) local_keys.env
    for base in (HERE, REPO if 'REPO' in globals() else HERE):
        p = os.path.join(base, "local_keys.env")
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() in ("GH_TOKEN", "GH_PAT", "GITHUB_TOKEN") and v.strip():
                                _TOKEN_SRC = "file"
                                return v.strip()
            except Exception:
                pass

    # 3) Windows 凭据管理器
    try:
        import ctypes
        import ctypes.wintypes as wt

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wt.DWORD), ("Type", wt.DWORD),
                ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
                ("LastWritten", wt.FILETIME), ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR),
            ]

        adv = ctypes.windll.advapi32
        pcred = ctypes.POINTER(CREDENTIAL)()
        if adv.CredReadW("git:https://github.com", 1, 0, ctypes.byref(pcred)):
            try:
                c = pcred.contents
                blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
                pw = blob.decode("utf-16-le").rstrip("\x00")
                if pw:
                    _TOKEN_SRC = "cm"
                    return pw
            finally:
                adv.CredFree(pcred)
    except Exception:
        pass
    return ""


# 优先级从上到下。判据细节见 `find_repo()`；**顺序只是最后的平手裁决**，
# 真正的胜负由「完整度 → 本机独有数据 → 是否同源」决定。
#
# ⚠️ 2026-09-16 修正：旧注释说「必须与远端同源」—— 那是基于已废弃的
#    `pull --rebase` 设计。现在 update.py 完全不拉取了（见其 git_sync_safe()），
#    「同源」已降级为加分项。当时正是这条过时判据导致选中了残缺的
#    `cs2-dash-push`（10 个文件、无 price_history.db）。
#
# **主仓库 = `C:\Users\Lenovo\cs2-runner-local`**：104 个文件、全脚本齐备、
# 持有 362 MB 的 price_history.db 与 local_keys.env。
CANDIDATES = [
    os.environ.get("CS2_REPO", ""),
    r"C:\Users\Lenovo\cs2-runner-local",
    r"C:\actions-runner\_work\cs2-dashboard\cs2-dashboard",
    HERE,
    r"C:\Users\Lenovo\cs2-dash-push",
    r"C:\Users\Lenovo\cs2-dashboard",
]

# 有这些运行时文件之一，说明这是「主工作仓库」而非只用于拉代码的镜像
_DATA_MARKERS = ("price_history.db", "buff_history.json", "eco_tracked.json")


def _git_ok(d):
    """目录是否是一个 git **真正能识别**的仓库。

    注意：只判断 os.path.isdir(d/.git) 是不够的 —— .git 目录可能残缺
    （例如缺 refs/），git 会报 'not a git repository'。必须实跑一次。
    """
    if not os.path.isdir(os.path.join(d, ".git")):
        return False
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=d, env=env,
                           capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, errors="replace",
                           timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _data_score(d):
    """该目录持有多少「本机独有数据」，越高越应该作为主仓库。"""
    n = 0
    for m in _DATA_MARKERS:
        p = os.path.join(d, m)
        try:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                n += 1
        except OSError:
            pass
    # price_history.db 权重最高（它是唯一不可再生的历史价格库）
    db = os.path.join(d, "price_history.db")
    try:
        if os.path.exists(db) and os.path.getsize(db) > 1_000_000:
            n += 5
    except OSError:
        pass
    return n


def _shares_history(d):
    """该仓库是否与远端**同源**（有 `origin/main` 引用可达）。

    这一条极重要：本地 root-commit 重建的仓库与远端没有共同祖先，
    每轮 `pull --rebase origin main` 都会退化成**全量重下整个仓库**。
    同源的仓库才会命中 fast-forward / 小增量。
    """
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(["git", "rev-parse", "--verify", "origin/main"],
                           cwd=d, env=env, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, errors="replace",
                           timeout=30)
        if r.returncode != 0:
            return False
        # 还要求能算出共同祖先（对象齐全）
        r2 = subprocess.run(["git", "merge-base", "HEAD", "origin/main"],
                            cwd=d, env=env, capture_output=True, text=True,
                            creationflags=CREATE_NO_WINDOW, errors="replace",
                            timeout=60)
        return r2.returncode == 0
    except Exception:
        return False


def _is_usable_repo(d):
    """目录可用 = 有 update.py 且 .git 真实可用"""
    if not d or not os.path.isdir(d):
        return False
    return (os.path.isfile(os.path.join(d, "update.py")) and _git_ok(d))


# 完整仓库应有的关键脚本。缺任何一个都说明这是个残缺/过期的副本，
# 跑起来会静默地把数据写到别处或直接失败。
_REQUIRED_SCRIPTS = (
    "update.py",
    "price_db.py",
    "updater_daemon.py",
    "generate_scan.py",
    "index_collector.py",
)


def _completeness(d):
    """仓库完整度 = 关键脚本齐备数 + 关键数据文件齐备数。

    ── 为什么需要这个（2026-09-16 踩坑）──────────────────────────────
    曾发现 `find_repo()` 选中了 `C:\\Users\\Lenovo\\cs2-dash-push`：
    它只有 10 个文件（缺 price_db.py / price_history.db / local_keys.env /
    index_collector.py / .github），`update.py` 也是 143 KB 的旧版
    （主仓库是 169 KB）。它却因为「同源」判据独占及格线而被选中，
    于是整个 30 分钟定时任务都在往一个**没有历史数据库**的残缺仓库里写数据 ——
    表面日志一切正常（`✔ update.py prices 完成 rc=0`），实际数据没进主库。
    ─────────────────────────────────────────────────────────────────
    """
    n = 0
    if not d or not os.path.isdir(d):
        return 0
    for f in _REQUIRED_SCRIPTS:
        if os.path.isfile(os.path.join(d, f)):
            n += 2
    for f in ("price_history.db", "local_keys.env", "holdings.json",
              "eco_tracked.json", "buff_history.json"):
        p = os.path.join(d, f)
        try:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                n += 1
        except OSError:
            pass
    return n


def find_repo():
    """选出主工作仓库。

    ⚠️ 判据在 2026-09-16 **整体改过**，务必先读这段再改。

    旧判据以 `_shares_history()`（与远端同源）为「及格线」一票否决，
    理由是"否则每轮 `pull --rebase` 会全量重下"。但那是**基于已废弃的设计**：
    现在 `update.py` 已经完全不做 fetch/pull/rebase 了（见其 `git_sync_safe()`
    的注释），推送由 push 独立完成，**根本不需要本地与远端同源**。
    继续拿它当及格线的唯一后果，就是让一个残缺旧仓库靠"同源"胜出。

    现在的判据（越靠前权重越高）：
      1. **完整度**（`_completeness`）—— 关键脚本 + 数据文件齐备程度
      2. **本机独有数据**（`_data_score`，price_history.db 权重最高）
      3. **与远端同源**（`_shares_history`）—— 降级为**加分项**，不再是及格线
      4. CANDIDATES 中的顺序（靠前的优先）

    这样 `cs2-runner-local`（104 个文件、全脚本、362MB 数据库）必然胜出，
    而 `cs2-dash-push`（10 个文件、无数据库）会被自然淘汰。
    """
    usable = [d for d in CANDIDATES if _is_usable_repo(d)]
    if not usable:
        return None

    def rank(d):
        idx = CANDIDATES.index(d)
        return (
            _completeness(d),                        # 完整度优先
            _data_score(d),                          # 本机独有数据
            1 if _shares_history(d) else 0,          # 同源仅作加分
            -idx,                                    # 靠前的候选优先
        )

    return max(usable, key=rank)


REPO = find_repo() or HERE

PYTHON = r"C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

# ── 周期（秒）──
PRICES_INTERVAL = 30 * 60      # 30 分钟：价格线（SKIP_AI=1，不调大模型）
ALL_INTERVAL = 6 * 60 * 60     # 6 小时：全量 + AI 深度分析
INDEX_INTERVAL = 2 * 60 * 60   # 2 小时：行情指数（原 update-index.yml，只改 index 两节）

# CREATE_NO_WINDOW 已上移到模块前部（见 _TOKEN_SRC 附近），此处不再重复定义。


# ══════════════════ 日志 ══════════════════
def _logfile():
    os.makedirs(LOGDIR, exist_ok=True)
    return os.path.join(LOGDIR, "updater_%s.log" % datetime.now().strftime("%Y-%m-%d"))


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %-5s %s" % (ts, level, msg)
    # ⚠️ print 必须单独包异常保护（2026-09-16 实测踩坑）：
    #    daemon 由计划任务以 DETACHED | CREATE_NO_WINDOW 拉起，
    #    此时 stdout 句柄可能无效 → print 抛 OSError / UnicodeEncodeError。
    #    原先 print 写在 try **之外**，一抛异常就直接跳过下面的写文件，
    #    于是日志断在半截 —— 排查时看到的现象正是「daemon 打印到某一行就没了」，
    #    而真正的原因（异常）因为没能落盘而完全不可见。
    #    日志是本进程唯一的可观测通道，任何情况下都必须保证落盘。
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_logfile(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ══════════════════ 状态持久化 ══════════════════
def load_state():
    try:
        with open(STATEFILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    st["saved_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = STATEFILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATEFILE)
    except Exception as e:
        log("写状态失败: %s" % e, "WARN")


# ══════════════════ 单实例锁 ══════════════════
def acquire_lock():
    """防止多个调度器同时跑（用 PID 文件）。"""
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE, "r") as f:
                old = int(f.read().strip())
            # 检查该 PID 是否还活着
            alive = False
            try:
                out = subprocess.run(
                    ["tasklist", "/FI", "PID eq %d" % old, "/NH"],
                    capture_output=True, creationflags=CREATE_NO_WINDOW)
                # ⚠️ 不要用 text=True（2026-09-16 实测踩坑）：
                #    中文 Windows 的 tasklist 输出是 GBK，而本环境强制 UTF-8，
                #    subprocess 的后台 reader 线程解码时抛 UnicodeDecodeError →
                #    stdout 拿不到内容 → 恒判"PID 已失效" → 每次都会误杀重启。
                #    PID 是纯 ASCII 数字，直接在 bytes 里搜，彻底绕开编码问题。
                alive = str(old).encode("ascii") in (out.stdout or b"")
            except Exception:
                alive = True
            if alive and old != os.getpid():
                log("已有调度器在运行 (PID=%d)，退出。" % old, "ERROR")
                return False
        except Exception:
            pass
    try:
        with open(LOCKFILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log("无法创建锁文件: %s" % e, "ERROR")
        return False


def release_lock():
    try:
        if os.path.exists(LOCKFILE):
            os.remove(LOCKFILE)
    except Exception:
        pass


# ══════════════════ git 同步 ══════════════════
def _kill_tree(pid):
    """强杀进程树。

    ⚠️ Windows 上 `subprocess.run(timeout=...)` 超时后只会 kill **直接子进程**；
    git fetch 的真实跑腿进程是它再 fork 出来的 `git-remote-https` / `index-pack`，
    这些孙进程会变成孤儿继续跑、继续占着 .git 的锁，于是主进程虽然「超时返回」，
    仓库却仍被锁住，下一轮 fetch 直接失败。必须整棵树杀掉。
    """
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW,
                       timeout=30)
    except Exception:
        pass


def _git(*args, timeout=60):
    """跑一条 git 命令，带**可靠的**超时（超时则连同孙进程一起杀掉）。

    输出按**二进制**收，再手动解码：git 在中文 Windows 上会用 GBK 写进度，
    若交给 Popen 的 text 层解码，reader 线程会抛 UnicodeDecodeError（且那个
    异常发生在后台线程里，主流程只看到一句莫名其妙的 NoneType 报错）。
    """
    env = {**os.environ,
           "GIT_TERMINAL_PROMPT": "0",
           "GIT_ASKPASS": "echo",
           "GCM_INTERACTIVE": "never"}
    p = subprocess.Popen(["git"] + list(args), cwd=REPO, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=CREATE_NO_WINDOW)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid)
        try:
            p.communicate(timeout=15)
        except Exception:
            pass
        raise

    def dec(b):
        if not b:
            return ""
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                return b.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return b.decode("utf-8", "replace")

    return subprocess.CompletedProcess(p.args, p.returncode, dec(out), dec(err))


def git_sync():
    """运行前的 git 健康检查 —— **不做任何网络操作**。

    ⚠️ 2026-09-16 决策：彻底放弃 git fetch（与 update.py 的 git_sync_safe 保持一致）。
    原实现是「探测式 fetch（--depth=1，超时 120s，失败重试 2 次）」，实测有害无益：

      1) **本仓库的 fetch 从未真正落过对象**：它打印
         `* [new branch] main -> origin/main` 且 rc=0，但 `cat-file` 取不到对象、
         `fsck` 报 invalid sha1 pointer。根因是 `update-ref` 在 Windows 上
         中间目录缺失时**静默失败**（rc=0 却不建 ref），而 git fetch 内部正用它写 ref。
      2) **慢链路必超时**：本机到 GitHub 实测带宽仅 ~20 KB/s，--depth=1 也拉不动；
         白等 120s×2（外加 sleep 5s+10s）≈ 4.5 分钟，还会占住 .git 锁，
         把 30 分钟的 prices 周期彻底拖死。
      3) **远端比本地旧**：fetch 回来只会覆盖更新的数据。

    daemon 的职责是「按时跑 update.py」，而 update.py 自身已完全不做
    fetch/pull/rebase，推送由它内部的 push_all() 完成 —— 无需预先拉取。
    对齐远端这件事，由 push 端单向完成即可。

    因此这里只留一次「本地对象库是否自足」的检查，不碰网络。
    """
    # 本地对象库是否自足（有 HEAD 且能解析），决定后续 git 步骤能否安全进行
    try:
        if _git("rev-parse", "--verify", "HEAD", timeout=30).returncode != 0:
            log("本地 HEAD 不可解析，跳过后续 git 步骤", "WARN")
            return False
    except Exception as e:
        log("git 不可用（%s），跳过 git 步骤" % type(e).__name__, "WARN")
        return False

    return True



# ══════════════════ 执行一次更新 ══════════════════
def run_update(mode):
    """调用 update.py <mode>。不设 GITHUB_ACTIONS → 走本机分支自动 push。
    mode='index' 特殊：调用 index_collector.py（原 update-index.yml 的任务）。"""
    t0 = time.time()
    started = datetime.now().strftime("%H:%M:%S")
    log("─" * 58)
    log("▶ 开始 %s  (%s)" % ("index_collector.py" if mode == "index" else "update.py " + mode, started))

    git_sync()

    env = {**os.environ}
    env.pop("GITHUB_ACTIONS", None)        # ★ 关键：强制走「本机」推送分支
    env.pop("GITHUB_TOKEN", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["GCM_INTERACTIVE"] = "never"

    # update.py 的 git_push_locally 用 GH_TOKEN 拼 Authorization 头。
    # Actions 环境里由 Secrets 注入；本机运行时需要我们自己补上，
    # 否则会退化成「空 credential helper」直接推失败。
    if not env.get("GH_TOKEN"):
        tok = _local_github_token()
        if tok:
            env["GH_TOKEN"] = tok
            log("已注入 GH_TOKEN（来自 %s）" % ("local_keys.env" if _TOKEN_SRC == "file"
                                              else "Windows 凭据管理器"))
        else:
            log("⚠️ 未取到 GitHub token，push 可能失败（可写 local_keys.env）", "WARN")

    if mode == "prices":
        env["SKIP_AI"] = "1"               # 高频线不调大模型
        env["ENRICH_BUFF"] = "1"
    env.setdefault("ENRICH_BUFF", "1")

    if mode == "index":
        cmd = [PYTHON, "index_collector.py"]
    else:
        cmd = [PYTHON, "update.py", mode]

    logpath = os.path.join(LOGDIR, "run_%s_%s.log" % (
        mode, datetime.now().strftime("%Y%m%d_%H%M%S")))
    # 单次更新的硬上限：超过就杀掉（连同 git 孙进程），避免永久占住仓库。
    # all 模式含 AI 分析、历史约 2 小时，给足 3 小时。
    hard_timeout = 3 * 3600 if mode == "all" else 3600
    try:
        with open(logpath, "w", encoding="utf-8", errors="replace") as lf:
            p = subprocess.Popen(cmd, cwd=REPO, env=env,
                                 stdout=lf, stderr=subprocess.STDOUT,
                                 creationflags=CREATE_NO_WINDOW)
            try:
                rc = p.wait(timeout=hard_timeout)
            except subprocess.TimeoutExpired:
                log("%s 超过 %d 分钟硬上限，强制终止" % (mode, hard_timeout // 60), "ERROR")
                _kill_tree(p.pid)
                try:
                    p.wait(timeout=30)
                except Exception:
                    pass
                rc = -9
    except Exception as e:
        log("启动失败: %s" % e, "ERROR")
        return False, 0

    # index_collector.py 不自带 push，需在此补一次
    if mode == "index" and rc == 0:
        _commit_push("chore: market index %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))

    dur = time.time() - t0
    tail = ""
    try:
        with open(logpath, "r", encoding="utf-8", errors="replace") as lf:
            lines = lf.read().splitlines()
        tail = " | ".join([l for l in lines[-4:] if l.strip()])[:220]
    except Exception:
        pass

    label = "index_collector.py" if mode == "index" else "update.py %s" % mode
    if rc == 0:
        log("✔ %s 完成  用时 %.0f 秒  rc=0" % (label, dur))
        if tail:
            log("   末尾: %s" % tail)
        return True, dur
    else:
        log("✘ %s 失败  rc=%d  用时 %.0f 秒" % (label, rc, dur), "ERROR")
        if tail:
            log("   末尾: %s" % tail, "ERROR")
        return False, dur


def _commit_push(message):
    """给不自带 push 的脚本（index_collector.py）补一次提交推送。

    ⚠️ 2026-09-16 修复两个缺陷（此前 index **每次**推送都失败）：
      1. **没有注入任何凭据**，只设了"禁止交互"。于是 `git push` 只能索要密码，
         在非交互环境下必然失败：
             fatal: Cannot prompt because user interactivity has been disabled.
         这正是日志里 `✘ index 推送失败` 反复出现的原因；
         而 prices 之所以没事，是因为它走 update.py 内部的 `_git_auth_args()`
         （那里注入了认证）。→ 现在与 update.py 保持一致。
         ⚠️ 必须用 HTTP **Basic**（`x-access-token:<token>`）：
            `Authorization: Bearer` 是 GitHub *API* 的格式，git smart HTTP 端点
            不认，会退化成交互式索要密码。
      2. **不再 `pull --rebase`**：rebase 会重写 refs/，一旦被超时强杀就会清空
         整个 refs/，让仓库变成 "not a git repository"；而且远端数据可能更旧，
         rebase 进来只会覆盖新数据。改为「本地提交 → 直接 push」——
         push 不需要远端对象在本地存在。
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo",
           "GCM_INTERACTIVE": "never"}

    # 注入 HTTP Basic 认证；用 `-c` 传参，不把 token 落到 .git/config 里
    auth = []
    tok = _local_github_token()
    if tok:
        import base64 as _b64
        _cred = _b64.b64encode(
            ('x-access-token:' + tok).encode('utf-8')).decode('ascii')
        auth = ['-c', 'http.extraHeader=Authorization: Basic ' + _cred]
    else:
        log("   ⚠️ 未取到 GitHub token，index 推送可能失败", "WARN")

    def g(*args, check=False):
        r = subprocess.run(["git"] + auth + list(args), cwd=REPO, env=env,
                           capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, errors="replace")
        if check and r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "")[:200])
        return r
    try:
        g("add", "-A")
        if g("diff", "--cached", "--quiet").returncode == 0:
            log("   index 无变更，跳过提交")
            return
        g("commit", "-m", message, check=True)
        g("push", "origin", "main", check=True)
        log("   ✔ index 已推送")
    except Exception as e:
        log("   ✘ index 推送失败: %s" % e, "ERROR")


# ══════════════════ 主循环 ══════════════════
def main_loop():
    if not acquire_lock():
        return 1
    log("=" * 58)
    log("CS2 本机更新调度器启动  PID=%d" % os.getpid())
    log("仓库: %s" % REPO)
    log("Python: %s" % PYTHON)
    log("周期: prices 每 %d 分钟 / index 每 %d 小时 / all 每 %d 小时" % (
        PRICES_INTERVAL // 60, INDEX_INTERVAL // 3600, ALL_INTERVAL // 3600))

    st = load_state()
    now0 = time.time()
    # 首次启动：prices 立刻跑；index/all 错开，避免一上来三个一起挤
    last_prices = st.get("last_prices_ts", 0.0)
    last_all = st.get("last_all_ts", now0 - ALL_INTERVAL + 20 * 60)      # 首次 20 分钟后
    last_index = st.get("last_index_ts", now0 - INDEX_INTERVAL + 10 * 60)  # 首次 10 分钟后

    log("上次 prices: %s" % (datetime.fromtimestamp(last_prices).strftime("%Y-%m-%d %H:%M")
                            if last_prices else "从未"))
    log("上次 index : %s" % datetime.fromtimestamp(last_index).strftime("%Y-%m-%d %H:%M"))
    log("上次 all   : %s" % datetime.fromtimestamp(last_all).strftime("%Y-%m-%d %H:%M"))

    fails = {"prices": 0, "index": 0, "all": 0}

    try:
        while True:
            # ---- all（最重，优先级最高）----
            if time.time() - last_all >= ALL_INTERVAL:
                ok, _ = run_update("all")
                last_all = time.time()
                st["last_all_ts"] = last_all
                fails["all"] = 0 if ok else fails["all"] + 1
                st["fails_all"] = fails["all"]
                save_state(st)

            # ---- index ----
            if time.time() - last_index >= INDEX_INTERVAL:
                ok, _ = run_update("index")
                last_index = time.time()
                st["last_index_ts"] = last_index
                fails["index"] = 0 if ok else fails["index"] + 1
                st["fails_index"] = fails["index"]
                save_state(st)

            # ---- prices（最高频）----
            if time.time() - last_prices >= PRICES_INTERVAL:
                ok, _ = run_update("prices")
                last_prices = time.time()
                st["last_prices_ts"] = last_prices
                fails["prices"] = 0 if ok else fails["prices"] + 1
                st["fails_prices"] = fails["prices"]
                save_state(st)

            # 睡到下一个最近的执行点（最多 5 分钟，便于快速响应）
            t = time.time()
            nxt = min(last_prices + PRICES_INTERVAL - t,
                      last_index + INDEX_INTERVAL - t,
                      last_all + ALL_INTERVAL - t)
            wait = min(max(30, nxt), 300)
            log("下次检查 %.0f 秒后 (prices %.0f 分 / index %.0f 分 / all %.0f 分)" % (
                wait,
                max(0, last_prices + PRICES_INTERVAL - t) / 60,
                max(0, last_index + INDEX_INTERVAL - t) / 60,
                max(0, last_all + ALL_INTERVAL - t) / 60))
            time.sleep(wait)

    except KeyboardInterrupt:
        log("收到中断，退出。")
    except Exception:
        log("主循环异常:\n%s" % traceback.format_exc(), "ERROR")
    finally:
        release_lock()
    return 0


def show_status():
    st = load_state()
    print("=" * 58)
    print("CS2 本机更新调度器 · 状态")
    print("=" * 58)
    print("仓库      : %s" % REPO)
    print("Python    : %s" % PYTHON)
    print("状态文件  : %s" % STATEFILE)
    print()
    for key, label in [("last_prices_ts", "上次 prices"),
                       ("last_index_ts", "上次 index"),
                       ("last_all_ts", "上次 all")]:
        ts = st.get(key)
        if ts:
            dt = datetime.fromtimestamp(ts)
            ago = (datetime.now() - dt).total_seconds() / 60
            print("  %-12s %s  (%.0f 分钟前)" % (label, dt.strftime("%Y-%m-%d %H:%M:%S"), ago))
        else:
            print("  %-12s 从未运行" % label)
    print("  连续失败     prices=%d  index=%d  all=%d" % (
        st.get("fails_prices", 0), st.get("fails_index", 0), st.get("fails_all", 0)))
    print()
    # 锁状态
    if os.path.exists(LOCKFILE):
        with open(LOCKFILE) as f:
            print("  调度器进程   PID=%s (运行中)" % f.read().strip())
    else:
        print("  调度器进程   未运行")
    return 0


def watchdog():
    """计划任务调用：确认常驻调度器还活着，不在则拉起。

    返回 0 = 已在运行；1 = 刚拉起。
    """
    alive_pid = None
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE) as f:
                alive_pid = int(f.read().strip())
        except Exception:
            alive_pid = None
    if alive_pid:
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % alive_pid, "/NH"],
                                 capture_output=True,
                                 creationflags=CREATE_NO_WINDOW)
            # ⚠️ 不要用 text=True（2026-09-16 实测踩坑，见 acquire_lock 同名注释）：
            #    中文 Windows 的 tasklist 输出是 GBK，本环境强制 UTF-8 →
            #    后台 reader 线程解码抛 UnicodeDecodeError → stdout 为空 →
            #    恒判"已失效" → 每 15 分钟误杀重启一次正在干活的调度器。
            #    PID 是纯 ASCII 数字，直接在 bytes 里搜最稳。
            if str(alive_pid).encode("ascii") in (out.stdout or b""):
                return 0                      # 活着，什么都不做
        except Exception:
            pass
        log("看门狗: 锁文件 PID=%s 已失效，清理并重启" % alive_pid, "WARN")
        try:
            os.remove(LOCKFILE)
        except Exception:
            pass

    log("看门狗: 未发现运行中的调度器，正在拉起", "WARN")
    pyw = PYTHON.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = PYTHON
    DETACHED = 0x00000008
    try:
        subprocess.Popen([pyw, os.path.join(HERE, "updater_daemon.py")],
                         cwd=REPO, creationflags=DETACHED | CREATE_NO_WINDOW,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        return 1
    except Exception as e:
        log("看门狗: 拉起失败 %s" % e, "ERROR")
        return 2


def main():
    ap = argparse.ArgumentParser(description="CS2 看板本机定时更新调度器")
    ap.add_argument("--once", choices=["prices", "index", "all"], help="只执行一次指定模式")
    ap.add_argument("--status", action="store_true", help="显示状态")
    ap.add_argument("--watchdog", action="store_true",
                    help="巡检：进程不在则拉起（供计划任务调用）")
    args = ap.parse_args()

    if args.status:
        return show_status()
    if args.watchdog:
        return watchdog()
    if args.once:
        log("手动执行一次: %s" % args.once)
        ok, _ = run_update(args.once)
        return 0 if ok else 1
    return main_loop()


if __name__ == "__main__":
    sys.exit(main())
