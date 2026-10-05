# CS2 看板 · 服务器迁移 Runbook

> 目标：把采集/推送从旧机（`82.156.128.138`，北京 2C2G）迁到新机（上海 4C4G，腾讯云轻量）。
> 状态：2026-10-04 已完成迁移前准备与风险核对；**新机购买后按本文执行**。
> 关键约束：新机**不要 `git clone`**（腾讯云→github.com:443 被限速，509M 的 .git 拉不动）。

## 0. 迁移基线（旧机实测，2026-10-04）

| 项 | 值 |
|---|---|
| 系统 | Ubuntu 24.04.4 LTS / kernel 6.8.0-124 |
| 规格 | 2C / 1.9G RAM / 50G 盘（已用 19G） |
| Python | venv 3.12.3，**依赖只有 6 个**：requests / pycryptodome / certifi / charset-normalizer / idna / urllib3 |
| 仓库 | `https://github.com/hintime/cs2-dashboard.git`，分支 `main` |
| 数据 | `price_history.db` 1.2GB（**仅存旧机**）/ `market_history` 34M / `index_history` 748K / 顶层 42 个 JSON |
| 密钥 | `local_keys.env` 11 个键：ZHIPU_KEY / STEAMDT_KEY / CSQ_API_TOKEN / FIREPULSE_KEY / AI_PROVIDER_FAST / AI_PROVIDER_QUALITY / AI_FALLBACK_CLOUD / WECOM_CORP_ID / WECOM_AGENT_ID / WECOM_SECRET / GH_TOKEN |
| 定时任务 | 7 条 cron（见 §3），已把 `push_retry.sh` 停用（改 API 推送） |
| 快照 | `/home/ubuntu/cs2-snapshots/snapshot.sh`（每日 4:15）——**目录也要一起搬** |

## 1. 迁移风险清单（务必逐条处理）

| # | 风险 | 影响 | 处理 |
|---|---|---|---|
| R1 | **CSQAQ token 是 IP 白名单**（绑旧机 IP） | 新机采集不到主数据源 | 在 CSQAQ 后台把白名单换成**新机公网 IP**（唯一需要你手动做的外部操作） |
| R2 | **新机不能 `git clone`**（github.com:443 限速） | 无法用常规方式取代码 | 用 `github_api_fetch.py`（走 api.github.com，已实测可用）**或** 旧机/本机 scp 直传代码 |
| R3 | **`price_history.db` 1.2GB 只在旧机**（GitHub 只有旧快照，>100MB API 上限推不上去） | 丢失历史价格数据，Kronos 无语料 | **旧机 → 新机直传**（gzip 后约 300MB，3M 带宽约 13-15 分钟） |
| R4 | `tools/deploy_cron.py`、`cs2_backup.py` 硬编码旧 IP | 从本机推 cron/备份时连错机器 | 迁移后把 `HOST` 改成新 IP（服务器自身运行代码不引用自己 IP，采集不受影响） |
| R5 | venv / cron / 目录 / 快照脚本 | 新机跑不起来 | 跑 `bootstrap_new_server.sh`（装 6 个依赖 + 建目录 + 校验密钥） |
| R6 | CF Worker（cs2-dashboard-api） | —— | **不受影响**：Worker 是 serverless，服务器通过固定域名推它，不依赖服务器 IP |
| R7 | 旧机 10/19 到期 | 白花钱 | 迁移验证通过后**不续费**旧机 |

## 2. 数据/代码搬迁（两条路径，二选一）

### 路径 A（推荐，最快）：旧机 → 新机 直传
在一台能同时 ssh 两台机器的地方（**你的本机**，宽带快）执行：
```bash
# 1) 代码 + 小数据（不含 db）
rsync -avz --exclude 'price_history.db*' --exclude '.git' --exclude 'venv' \
      --exclude 'logs' ubuntu@OLD_IP:/home/ubuntu/cs2-run/ \
      ubuntu@NEW_IP:/home/ubuntu/cs2-run/
# 2) 1.2GB 主库（单独传，走 gzip）
ssh OLD_IP "sqlite3 price_history.db '.backup /tmp/ph.db' && gzip -1 -f /tmp/ph.db"
scp OLD_IP:/tmp/ph.db.gz /tmp/ph.db.gz
scp /tmp/ph.db.gz NEW_IP:/tmp/ && ssh NEW_IP "gzip -d /tmp/ph.db.gz && mv ph.db /home/ubuntu/cs2-run/price_history.db"
# 3) 密钥 + 快照脚本
scp OLD_IP:/home/ubuntu/cs2-run/local_keys.env NEW_IP:/home/ubuntu/cs2-run/
rsync -avz ubuntu@OLD_IP:/home/ubuntu/cs2-snapshots/ NEW:/home/ubuntu/cs2-snapshots/
```

### 路径 B（兜底）：新机用 API fetch 还原代码+JSON，db 仍需直传
```bash
# 新机上（代码目录已存在放工具的位置）
python github_api_fetch.py --repo hintime/cs2-dashboard --ref main \
       --dest /home/ubuntu/cs2-run --exclude price_history.db
# ⚠ 该工具已实测可用，但约 0.5-1 文件/秒，270 文件需几分钟；且【不含 db】
```

## 3. crontab（新机）

bootstrap 的 `--install-cron` 会从 `tools/migration/crontab.new` 安装。7 条任务：
```
*/30 * * * *  watchdog/check.py（系统 python3）
*/30 * * * *  run_cycle.sh prices
0 */2 * * * *  run_cycle.sh index
0 */6 * * * *  run_cycle.sh all
15 * * * *  run_cycle.sh history
15 4 * * *  snapshot.sh
0 9 * * *  tools/kronos_ready.py --push
（push_retry 已停用）
```
**切换顺序**：先只开 watchdog，确认新机数据产出正常，再开 prices/all/history。

## 4. 切换与验证清单

- [ ] R1：CSQAQ 白名单已换成新机 IP
- [ ] 新机 `bash tools/migration/bootstrap_new_server.sh --install-cron`
- [ ] 数据（尤其 db）已到位，`ls -l price_history.db` ≈ 1.2GB
- [ ] 手动跑一轮 `tools/run_cycle.sh prices`，看 `logs/cron_prices.log` 出现 `[PUSH] API 通道推送成功`
- [ ] 企微收到新机 watchdog 心跳（无 stale 告警）
- [ ] GitHub `data_status.json` 的 updated 刷新为新机时间
- [ ] 旧机**停掉 cron**（防双写同一 main），观察 1-2 轮无异常
- [ ] 旧机 10/19 **不续费**

## 5. 回滚
新机任一环节失败 → 旧机 cron 重新启用即可（数据本就还在旧机 db）。旧机在验证期内**不要删、不要重装**。
