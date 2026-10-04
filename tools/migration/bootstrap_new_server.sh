#!/usr/bin/env bash
# =============================================================================
# CS2 看板 · 新服务器 bootstrap（在【新机】上跑，代码+数据放好之后执行）
#
# 用法：
#   bash tools/migration/bootstrap_new_server.sh                 # 只装环境，不动 cron
#   bash tools/migration/bootstrap_new_server.sh --install-cron   # 装环境 + 恢复 crontab
#
# 前提：/home/ubuntu/cs2-run 下已有代码与数据（本脚本不负责传数据）。
# 幂等：可重复执行。
# =============================================================================
set -u
RUN=/home/ubuntu/cs2-run
VENV="$RUN/venv"
LOGDIR="$RUN/logs"

log(){ echo "[$(date '+%F %T')] $*"; }

# ── 0. 基本检查 ──────────────────────────────────────────────────────────
log "=== CS2 新机 bootstrap 开始 ==="
[ -d "$RUN" ] || { log "FATAL: $RUN 不存在（代码/数据还没放过来？）"; exit 1; }
log "系统: $(grep PRETTY /etc/os-release | cut -d= -f2- | tr -d '\"')  CPU:$(nproc)  内存:$(free -h | awk '/Mem:/{print $2}')"

# ── 1. 系统依赖（Ubuntu 24.04 自带 python3.12）─────────────────────────
log "--- 检查 python3 ---"
if ! command -v python3 >/dev/null 2>&1; then
  log "安装 python3 / python3-venv / git ..."
  sudo apt-get update -y >/dev/null 2>&1
  sudo apt-get install -y python3 python3-venv python3-pip git gzip >/dev/null 2>&1
fi
log "python3 = $(python3 --version)"

# ── 2. venv + 依赖（与旧机一致：6 个包，尽量少）─────────────────────────
log "--- 建 venv 并装依赖 ---"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || { log "FATAL: venv 创建失败"; exit 1; }
  log "venv 已创建"
else
  log "venv 已存在，跳过创建"
fi
# 旧机 pip freeze 实测只有这 6 个（2026-10-04）
"$VENV/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1
"$VENV/bin/python" -m pip install -q requests==2.34.2 pycryptodome==3.23.0 certifi==2026.7.22 \
    charset-normalizer==3.5.1 idna==3.20 urllib3==2.8.0 >/dev/null 2>&1
log "依赖已装：$("$VENV/bin/python" -m pip freeze | tr '\n' ' ')"

# ── 3. 目录 ─────────────────────────────────────────────────────────────
mkdir -p "$LOGDIR" "$RUN/watchdog" "$RUN/logs"
log "目录就绪: logs/ watchdog/"

# ── 4. 密钥自检（只查名字，不打印值）────────────────────────────────────
log "--- 密钥自检 ---"
KEYS="ZHIPU_KEY STEAMDT_KEY CSQ_API_TOKEN FIREPULSE_KEY AI_PROVIDER_FAST AI_PROVIDER_QUALITY AI_FALLBACK_CLOUD WECOM_CORP_ID WECOM_AGENT_ID WECOM_SECRET GH_TOKEN"
kf="$RUN/local_keys.env"
if [ -f "$kf" ]; then
  MISS=""
  for k in $KEYS; do grep -q "^$k=" "$kf" || MISS="$MISS $k"; done
  if [ -n "$MISS" ]; then log "警告：local_keys.env 缺少:$MISS （从旧机复制完整文件！）"; else log "密钥齐全（11 个）"; fi
else
  log "警告：local_keys.env 不存在 —— 必须从旧机复制，否则采集/AI/企微全废"
fi

# ── 5. 同步脚本硬编码 IP 提醒 ───────────────────────────────────────────
if grep -rn "82\.156\.128\.138" "$RUN/tools"/*.py >/dev/null 2>&1; then
  log "注意：tools/deploy_cron.py、cs2_backup.py 仍硬编码旧 IP —— 用本机跑 deploy_cron 时改成新 IP"
fi

# ── 6. cron（可选）──────────────────────────────────────────────────────
if [ "$1" = "--install-cron" ]; then
  log "--- 安装 crontab（从 $RUN/tools/migration/crontab.new）---"
  if [ -f "$RUN/tools/migration/crontab.new" ]; then
    crontab "$RUN/tools/migration/crontab.new" && log "crontab 已安装（先别开 flock 采集，等数据验完）"
  else
    log "找不到 crontab.new，跳过。请手工从旧机 crontab -l 复制并把 IP/路径核对一遍。"
  fi
else
  log "（未指定 --install-cron，跳过 cron 安装）"
fi

log "=== bootstrap 完成。下一步：放数据 → 验 db 连续性 → 再开 cron 采集 ==="
