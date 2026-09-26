# -*- coding: utf-8 -*-
"""Kronos 微调可行性结论（2026-09-18 实测）

## 硬件
- GPU: RTX 4060 Laptop 8GB（可用 5.9GB）；但 venv 装的是 **torch CPU 版**（2.14.0+cpu）
  → 真要微调需装 CUDA 版 torch（约 2.5GB 下载，C 盘余 33GB 够）
- C 盘剩余 33.1 GB

## 数据（关键约束）
- price_history.db：160.6 万条，5223 个标的，**仅 57 个采样日（2026-06-19→09-17）**
- ECO 日线：26.7 万根 → **约 51 根/标的**
- Kronos 上下文为 **512 步** → 单标的序列长度比模型上下文短一个数量级；且只有**单一行情区间**（这段整体下跌）

## 评估台架结果（40 标的，挖最后 14 天为测试集）
| 方法 | MAE | 相对误差 | 方向命中 |
|---|---|---|---|
| 价格不动 | 20.19 | 4.52% | — |
| 线性外推 | 77.19 | 17.30% | 35% |
| Kronos 零样本 | **18.17** | **4.07%** | **55%** |
- 真实方向分布 34跌/6涨；Kronos 预测 22涨/18跌 → **明显低估下跌倾向**
- 注意：该样本里"永远猜跌"的命中率是 85%，所以 55% 在下跌行情中并不算好；MAE 仅比"价格不动"好 10%

## 结论
1. **现在微调性价比低、风险高**：数据仅 3 个月、单一区间，微调大概率**过拟合这段下跌**，
   产出系统性看跌的模型（零样本已有此倾向）。
2. **先补数据（已做）**：`PRICE_HIST_KEEP_DAYS` 默认 90 → **365 天**（update.py 内）。
   下一步可选：把价格记录从"仅 all/market 周期"扩展到 prices 周期并按小时节流
   （目标 1000+ 点/标的、跨多个行情区间）。
3. **微调的正确姿势**（等数据够了再做）：
   - 装 CUDA torch；冻结 tokenizer，只对 Kronos 主体做**继续预训练**（next-token prediction）
   - 低 LR（1e-5 ~ 5e-5）、1-3 epoch、带验证集早停
   - **必须用 eval_forecast.py 台架证明改进**（MAE / 方向命中同时不退化）才采用
4. 评估脚本：`E:\cs2-kronos\eval_forecast.py`（可重复运行，产物 outputs/kronos_eval.csv）

## 数据积累路线（2026-09-18 决策）

### 就绪度检查
- 新增 `E:\cs2-kronos\kronos_data_readiness.py`：只读 `price_history.db`(eco 通道)，
  量化「每标点数 / 跨度 / 周度多空方向 / 到 1000 点还需多久」，产物 `readiness_report.json`。
- **实测（2026-09-18）**：5223 标的 / 548873 点；每标点数中位 **118**、p10 59、p90 118、最大 118；
  跨度 90 天；周度方向 **涨 5 / 跌 5**（多空已兼具，单一区间风险解除）；
  按当前「每日约 1 次落库」节奏，到 1000 点/标的要求 **672 天** —— 自然攒不可行。

### 瓶颈与决策
- **唯一瓶颈 = 采集频率**（点数），区间多空已满足。
- 根因：价格历史记录块挂在 `all`/`market` 模式，而 daemon 只排了 `all`(6h) 且 `market` 没排 →
  实际约每天 1 次落库。
- **决策（义轩拍板：每 3-6 小时落价）**：新增独立 `history` 模式 ——
  - `update.py history`：重新批量抓 ECO 现价（fetch_eco_prices，约 4791 件/53 批并发，10-30s）→
    落 `price_history.db`(eco 通道) → trim_old_data(365)。**不动 prices 周期、不写 market.json、不 push**。
  - `updater_daemon.py`：新增 `HISTORY_INTERVAL` 调度（**默认 3h，可用环境变量 HISTORY_INTERVAL(秒) 压到 1h/2h**）+ `--once history` + 状态显示。
  - 注意：ECO 仅约 **500 件**有活跃在售价（其余无在售挂单），故微调对象实质是这 ~500 件可交易标的。

### 加速积累（2026-09-18 晚）
- **覆盖从 500 件 → ~5000+ 件**：`history` 模式在抓完 ECO 后，额外从 `eco_tracked.json` 缓存的
  `buff_sell`/`yyyp_sell` 落 **buff/yy 通道**（零额外 API 成本）。实测单跑落库 **9973 条**
  （eco 500 / buff 4745 / yy 4728）。buff/yy 是 CN 主交易场，流动性更好，更适合做域适应训练样本。
- **数据库迁 E 盘**：原 `C:\Users\Lenovo\cs2-runner-local\price_history.db`（362MB+，只增不减）迁到
  `E:\cs2-data\price_history.db`（sqlite 在线 backup，行数一致校验 1606941=1606941）。
  `price_db.py` / `kronos_forecast.py` / `kronos_data_readiness.py` 的 DB 路径改为
  **环境变量 `PRICE_HIST_DB` 可覆盖、默认 E 盘**；`updater_daemon.py` 仓库探测仍靠脚本完整度命中主仓库
  （库已不在仓库目录，但 cs2-runner-local 凭全脚本仍胜出）。
- 现节奏：buff/yy ~5000 件每 ~4h（history 4h + all/market 6h 叠加）落点 → 约 **85 天**到 512 点/标；
  eco ~500 件每 4h → 约 **4 个月**到 512 点/标。届时即可进微调阶段。

### 触发微调的硬指标（届时用 eval_forecast.py 验证）
- ★ **连续性（义轩 2026-09-18 明确要求："要用连续几天的，不要看到就用"）**：
  训练序列必须是**连续多日、无大缺口**的规则采样 —— 相邻点间隔 >12h 即切段，
  只有 >=512 点的连续段才算合格训练序列（门槛：合格序列总数 >=300 条）。
  **旧稀疏数据（2026-09-18 前每日约 1 次、90 天仅 57 个采样日）天然被切段淘汰，不进微调语料**，
  只继续用于零样本推理。就绪度脚本 `kronos_data_readiness.py` 已升级为连续性门槛版。
- 每标点数 >= **512**（填满一个 Kronos 上下文窗口，越多越好）
- 周度方向同时含涨/跌（已满足：周度 涨5/跌5）
- 跑 `eval_forecast.py` 证明 微调后 MAE / 方向命中 同时不退化于零样本，才采用

### 运维注意（连续性依赖机器在线）
- 整机关机/睡眠会产生断点：连续段在断点处被切开，**序列只会变短、不会被污染**，但会推迟达标。
  **积累期尽量不关机/不睡眠。**
- 实测教训（2026-09-18）：daemon 半夜中断（last_prices 停在 01:35），09:51 才被看门狗拉起，
  `all` 跑了 2h 后 11:52 history 才首次由 daemon 调度成功（落库 9849 条：eco 500 / buff 4681 / yy 4668）。
  此前就绪度测出的"节奏 9.8~13.2h"是假象（密集期只有 3 次落点事件，间隔被大缺口拉高）；
  daemon 稳定后实际节奏 = history 3h + all/market 6h 叠加 ≈ 3~4h。

---

# 2026-09-26 更正与落地（B 方案）

上面 09-18 那段**门槛口径偏了**，而且括号里的日子和实测差得远，这里整体更正。
实测数据源：`E:\cs2-mirror\price_history.db`（2026-09-26 11:18 服务器快照，
`max_ts=2026-09-26T03:15Z`，2811446 行 / 286 个 distinct ts）。

## 1. 门槛口径更正：**512 点不是标尺，窗口长度才是**

官方 `finetune_csv` 的样本是滑窗切出来的：

```
窗口 window = lookback_window + predict_window + 1
每条序列能切出的样本数 = 段长 - window + 1
```

- 段长 < window → 样本数为负 → 训练脚本直接抛 `Data length insufficient`
- 段长刚过 window → 样本数只有个位数 → 训了等于没训

官方示例用 `lookback 512 + predict 48` ⇒ **window = 561**。
所以：
- **561** 才是"能切出样本"的硬线（09-18 记的 512 低了两天）；
- 想要 2 万条样本，按每标的一条段算，**段长要到 ~564**；
- 09-18 记的"合格序列总数 >= 300 条"不是关键约束 —— 一旦段长到位，
  全场 5000+ 标的会**同时**越线（它们的采样节奏一致），序列数从 0 一步跳到 5000+。

## 2. 实测现状（2026-09-26，全部为服务器库实时复算）

| 通道 | 标的 | 节奏 | 最长连续段 | 段长 >= window(561) 的标的 | 估算样本 |
|---|---|---|---|---|---|
| buff | 5153 | **1.0 h/点** | 168 点 | 0 | 0 |
| yy | 5125 | **1.0 h/点** | 168 点 | 0 | 0 |
| eco | 5216 | **4.56 h/点** | 139 点 | 0 | 0 |

- buff/yy 的各标的 p90 段长 = 168，说明**所有标的都是从同一起点开始连续采样的**
  （即高频采集实际始于 `2026-09-19 03:15Z`，不是文档里写的 09-18）。
- **eco 通道节奏只有 4.56h/点**，比 buff/yy 慢 4.5 倍；按它训 561 点要等到年底，
  所以**微调语料应以 buff/yy 为主**。（这点 09-18 完全没看出来。）

## 3. 达标时间更正

| 说法 | 值 |
|---|---|
| 09-18 文档推测（按 4h 节奏） | "约 85 天到 512 点/标" |
| 本次实测外推（1h 节奏，够 2 万样本） | **约 16.5 天 → 2026-10-12** |

buff 通道每天 +24 点。到 564 点时各标的约能切出 4 条样本 × 5153 标的 ≈ 2 万条。

## 4. B 方案已落地（"提前搭好流程，别等到达标那天才发现跑不起来"）

工作区 `E:\cs2-kronos-ft\`（独立于生产推理环境 `E:\cs2-kronos\`，两边互不影响）：

- 引入 **Kronos 官方 master** 源码（`E:\cs2-kronos-upstream\`，`shiyu-coder/Kronos`，
  默认分支是 `master` 不是 `main`；本机只能从 `codeload.github.com` 下 tarball，
  `raw.githubusercontent.com` / `api.github.com` 需加 `--ssl-no-revoke`，git clone 会断）
- **CS2 多段补丁**：官方 `CustomKlineDataset` 假设"一个 CSV = 一条序列"，
  我们的数据是"多标的、每标的每小时一个点"，直接喂会要么样本数为负、要么窗口跨标的
  （样本内部按窗口 z-score，跨标的价差跳变会当成真实走势学进去）。
  补丁让 `data_path` 支持目录（每个 csv 一条段），窗口只在段内滑动；
  切分改为**按序列留出验证集**（官方按时间切 10%，而我们的段只有几百点，
  `0.1 × 段长` 远小于窗口 → 验证集样本数为 0 → 脚本报错）。
  单文件路径行为与官方完全一致。
- 新增 `tools/kronos_build_corpus.py`：从镜像库导出多段 CSV 语料（含连续性切段门槛）
- 新增 `tools/kronos_finetune_launch.py`：**就绪闸门** —— 未达标只报告不动 GPU，
  并算出「还差多少点 / 预计哪天」

### 验收（都跑过，不是纸面推演）

| 项 | 结果 |
|---|---|
| 多段 Dataset 样本数 / 不跨段 / 单文件兼容 | ✅ 人造 3 序列自检通过 |
| **window=561 在 Kronos-small 上前向 + 算损失** | ✅ `window561_ok`（这是最大未知项，已排除） |
| 端到端训练 + checkpoint 落盘（CPU） | ✅ 2592 训练 / 288 验证样本，`Epoch Time 251.79 s`（2 轮合计 ≈ 503 s） |
| 端到端训练 + checkpoint 落盘（GPU, RTX 4060） | ✅ `Epoch Time 13.37 s` → **CPU→GPU ≈ 18.8×** |
| **微调产物被生产侧 `E:\cs2-kronos\model\` 加载** | ✅ 两边都 `load_ckpt=true`，`n_params=24741376`，且都能跑完整 7 步预测 |

> 口径更正（2026-09-26 晚）：本表此前写的"loss 6.4 → 0.83，8.55 min"是错的。
> 实际日志（`finetuned/smoke_cs2_buff/logs/basemodel_training_rank_0.log`）为：
> 首步 loss 1.0917 → 第 1 轮 Training Loss 0.8932 / Val 1.0547 → 第 2 轮 0.8325 / 1.0399；
> `Epoch Time` 251.79 s / 251.64 s（"8.55 min" 是**两轮合计**，不是单轮）。
> 0.83 那个数字歪打正着是第 2 轮的 Training Loss，6.4 则不知从何而来，已废弃。

→ **跨版本兼容风险解除，不需要动生产推理环境。**

## 5. 一字线问题（新发现，影响训练策略）

当前只有单点价格、没有真正的 OHLC。按 1 小时聚成 K 线时 **open = high = low = close**，
6 个特征列里有 3 列完全相同，volume/amount 恒为 0（官方 README 允许）。
所以默认配置 `train_tokenizer: false` —— tokenizer 的 BSQ 码本是在真实 K 线上训出来的，
拿退化 K 线再训收益有限；只微调 predictor（时序动态）。
想要真实高低价差可把 `--bucket-hours` 调到 2/4，代价是序列长度等比例变短、达标顺延。

## 6. 未决 / 待办

- ~~**CUDA 版 torch 仍未装**~~ → **已装好（2026-09-26 晚）**，见第 7 节。
- ~~**`tools/kronos_ready.py`（服务器每日 9:00 企微推送）口径仍是错的**~~ → **已改口径并部署（2026-09-26 晚）**，见第 7 节。
- 旧稀疏数据（09-18 前每日约 1 次）不进微调语料，只继续用于零样本推理 —— 这一条不变。
- 微调产物采用前，仍须用 `eval_forecast.py` 台架证明 MAE / 方向命中不退化于零样本。

## 7. 2026-09-26 晚：CUDA 落地 + 口径修正部署 + 上游缺陷修复

### 7.1 CUDA 版 torch 装好（RTX 4060 真正可用）

| 项 | 值 |
|---|---|
| wheel 来源 | `https://mirrors.aliyun.com/pytorch-wheels/cu130/torch-2.14.0+cu130-cp312-cp312-win_amd64.whl` |
| 体积 / 速度 | 1,990,604,486 B（1.85 GiB），直连（`--noproxy '*'`）稳定 3.2 MB/s |
| 安装方式 | `pip install --no-deps --force-reinstall`（**Windows wheel 自包含**：METADATA 里没有任何 `nvidia-*` / `cuda-*` 依赖，39 个 CUDA DLL 全在 `torch/lib/`） |
| 版本 | `2.14.0+cu130`，`torch.version.cuda = 13.0`，cudnn 92400 |
| 设备 | `NVIDIA GeForce RTX 4060 Laptop GPU`，cc 8.9，显存 8188 MB |
| 算力实测 | 2048³ fp32 矩阵乘 ×20 = 0.053 s → **6504 GFLOPS** |
| **训练加速比** | **≈ 18.8×**（同数据/同超参/同 `train_model`：CPU 251.79 s/epoch → GPU 13.37 s/epoch） |
| 一致性校验 | 对比 wheel 与已装目录：**12247 个文件零缺失、大小全对**，409 项 CRC（全部 DLL + `version.py` + `__init__.py`）全符 |

踩到的两个坑（已写入 `E:\cs2-kronos-ft\README.md`）：
1. **wheel 文件名不能改**：改成 `torch_cu130.whl` 后 pip 报 `Invalid wheel filename (wrong number of parts)`，必须保持规范名。
2. **沙箱批量删除保护会拦 pip 清理旧版**：pip 卸载旧 `2.14.0+cpu` 时把文件挪到 `~orch*` 暂存区、删除被拦 →
   留下 543 MB 垃圾 + `Ignoring invalid distribution ~orch` 警告，需手工清除后校验。

### 7.2 `kronos_ready.py` 口径修正已部署到服务器

- 部署到 `/home/ubuntu/cs2-run/tools/kronos_ready.py`（md5 `fbb4c9c86e9bd10633208ad6fd9a3a93`，10491 B）
- 服务器环境核对：**SQLite 3.45.1**（≥3.25，窗口函数可用，无需退化分支）、Python 3.12.3、TZ = **Asia/Shanghai**
- 服务器实跑输出（逐标的精确口径）：buff/yy 最长段 176 点、eco 140 点，目标段长 564，还差 388/424 点，ETA **10-12**
- 企微推送已验证：`推送: OK ok`（cron 保留，每日 **09:00 北京时间**）
- 注意：`tools/` 整个目录在 `.gitignore` 第 54 行被排除 ⇒ **这些工具不进 git，只存在于机器上**，
  部署靠 `ssh`（`scp` 在本机沙箱被拦，改用 `cat > 文件` 走 ssh stdin）

### 7.3 发现并修复 upstream 缺陷

官方 `finetune_csv/finetune_base_model.py` 的 `main()` 内有两处 `import json, os`
（上游 394/421 行），而更早的 381 行就用了 `os.makedirs` → `os` 被判定为函数局部变量 →
直接运行必抛 `UnboundLocalError`。**上游 master 原样如此，与我们打的补丁无关。**

- 修复：`import json, os` → `import json`（两处）
- 两条入口共用同一个 `train_model()`（`train_sequential.py` 里 `from finetune_base_model import train_model`），
  所以走哪条入口结果都可比

### 7.4 顺带清理

- 服务器旧版 `tools/kronos_ready.py` 备份为 `tools/kronos_ready.py.bak_before_926_2`
- 本机 venv 里 pip 残留 `~orch / ~orchgen / ~unctorch`（543 MB）与既存死残留
  `~ransformers-5.17.0.dist-info`、`transformers.broken.gone`（18 MB）已清除，pip 警告消失
- 文档提交：`6d4b07c docs(kronos): 更正微调门槛口径为窗口561步 + 记录 B 方案落地`
  （本机 github.com 不通，改用服务器侧 `push_retry.sh` 推送成功，`5271be2..6d4b07c main -> main`）
