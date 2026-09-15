# CS2 看板 · 本机定时更新（替代 GitHub Actions）

> 2026-09-15 建立。原因：GitHub Actions 的 self-hosted runner 与 GitHub 的连接
> 在 07:29:54 UTC 断开后未能恢复，导致 `Update Prices` 连续 4 次调度（07:43/08:13/08:43/09:13）
> **全部未触发**，数据停更 2 小时以上。改用本机常驻调度器彻底绕开该问题。

---

## 为什么能这样替代

`update.py` **本身就是自包含的**：

```
main()
  ├─ git stash → git pull --rebase origin main        (自动同步远端)
  ├─ 抓取 ECO / SteamDT / CSQAQ 数据                   (本机网络)
  ├─ 写入 market.json / holdings.json / eco_tracked.json
  └─ push_all()
        └─ if os.environ.get('GITHUB_ACTIONS') and GH_TOKEN:
               # CI 模式：跳过内联推送，交给 workflow 的 git_ops.py
           else:
               # ★ 本机模式：自己 git commit + push（带 3 次重试）
               git_push_locally(...)
```

**关键点：只要不设置 `GITHUB_ACTIONS` 环境变量，`update.py` 就会走本机分支，自己完成 commit + push。**
所以本机调度器只需要「按时调用 update.py」这一件事。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `updater_daemon.py` | **核心调度器**（纯标准库，无第三方依赖） |
| `install_updater.bat` | 一键安装：后台启动 + 设置开机自启 |
| `stop_updater.bat` | 停止调度器 + 移除开机自启 |
| `logs/` | 运行日志（按日期分文件） |
| `.updater_state.json` | 状态记录（上次运行时间、失败计数） |
| `.updater.lock` | 单实例锁（存 PID） |

---

## 使用

### 安装（首次）
双击 `install_updater.bat`，或在命令行运行：
```bat
install_updater.bat
```
它会：
1. 用 `pythonw.exe` 在**后台无窗口**启动调度器
2. 写入注册表 `HKCU\...\Run`，实现**开机自启**
3. 之后每 30 分钟自动更新价格，每 6 小时全量更新

### 查看状态
```bat
python updater_daemon.py --status
```

### 手动跑一次
```bat
python updater_daemon.py --once prices
python updater_daemon.py --once all
```

### 停止
```bat
stop_updater.bat
```

### 日志
```
logs\updater_YYYY-MM-DD.log      调度器自身日志（何时触发、成功/失败）
logs\run_prices_YYYYMMDD_HHMMSS.log   update.py 的完整输出
```

---

## 周期设置

在 `updater_daemon.py` 顶部：
```python
PRICES_INTERVAL = 30 * 60      # 30 分钟（价格线，SKIP_AI=1，不调大模型）
ALL_INTERVAL    = 6 * 60 * 60  # 6 小时（含 AI 深度分析）
```

---

## 需要的环境变量

已在本机**用户级环境变量**中持久化的（无需重复设置）：

| 变量 | 状态 | 用途 |
|---|---|---|
| `ECO_PRIVATE_KEY_B64` | ✅ 已有 | ECO 价格（holdings.json） |
| `STEAMDT_KEY` | ✅ 已有 | BUFF / 悠悠比价 |

**⚠️ 仍需补齐的**：

| 变量 | 影响 |
|---|---|
| `CSQ_API_TOKEN` | **缺失会导致 Steam 独立基准价（`n_steam` / `n_dev_steam`）为空** |
| `ZHIPU_KEY` | 缺失则 6 小时的 `all` 模式无法生成 AI 分析（价格更新不受影响） |

补齐方式（PowerShell，设置后需重启调度器）：
```powershell
[Environment]::SetEnvironmentVariable('CSQ_API_TOKEN', '你的token', 'User')
[Environment]::SetEnvironmentVariable('ZHIPU_KEY', '你的key', 'User')
```

---

## 与 GitHub Actions 的关系

本调度器**完全独立于** GitHub Actions。原来的 3 个 workflow：

| workflow | 建议 |
|---|---|
| `update-prices.yml` | **可以停用**（本调度器接管） |
| `update-all.yml` | **可以停用**（本调度器接管） |
| `update-index.yml` | 跑在 `ubuntu-latest`（GitHub 托管），**不受 runner 问题影响，可保留** |

⚠️ 但注意：如果保留 `update-index.yml`，它与本调度器可能同时写 `market.json`。
`update.py` 内部有 `git pull --rebase` + 冲突自动解决，实测可共存，但**建议观察一次**。

要停用某个 workflow，把它的 `schedule:` 段注释掉即可（保留 `workflow_dispatch` 以便手动触发）。

---

## 故障排查

**Q: 数据不更新了？**
```bat
python updater_daemon.py --status     # 看上次运行时间
type logs\updater_YYYY-MM-DD.log      # 看错误
```

**Q: 提示「已有调度器在运行」？**
锁文件残留。确认进程真的没了之后，删除 `.updater.lock` 再启动。

**Q: push 失败？**
本机依赖 Windows 凭据管理器里的 GitHub 凭据。验证：
```bat
git -C . push origin main
```
若提示认证失败，需要重新登录 Git 凭据管理器。

**Q: 怎么确认真的推上去了？**
```bat
git log --oneline -3
git status
```
