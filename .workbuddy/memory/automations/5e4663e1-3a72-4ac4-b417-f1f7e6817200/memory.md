# 自动化执行记忆 — 本轮 all 跑通核查（9c6a5f1 + 6bcb042）

## 2026-09-19 18:40 首次执行
- 核查对象：`logs/updater_2026-09-19.log` + `logs/run_all_20260919_171340.log`（最新一轮）
- 结果：**6/7 通过，1 项失败（排行榜 401 未消除），判定无需回滚**
- 关键产出：定位到 401 的真根因是 `recommend.py` 依赖环境变量 `CSQ_API_TOKEN` 但
  无任何启动脚本注入（token 只存在于 `local_keys.env`，仅 buy_fill/csqaq_buy 会读）
- 详细结论已追加到 `E:\项目\2026-09-13-17-23-31\.workbuddy\memory\2026-09-19.md`
- 遗留待办：让 `recommend.py` 增加从 `local_keys.env` 回退取 token

## 复用要点（下次核查可直接照做）
- 本轮日志文件：`logs/run_all_<日期>_<HHMMSS>.log`，取 mtime 最大者；全文 200 行左右，可直接 Read
- 判断"某提交是否真跑到了"：比对**日志里的打印格式变化**，比"有没有报错"更可靠
  （本例：`price_up_1d p1` ×8 → `rank p1` ×4，一眼看出新代码生效）
- `git log -3` 看不到目标提交是常态（被定时 chore 提交顶掉），改用
  `git merge-base --is-ancestor <sha> HEAD` 判定 rc=0
- 体检三件套：`proxy_field_audit.py` / `rec_field_audit.py` / `lint.py`，均 rc=0 为绿
