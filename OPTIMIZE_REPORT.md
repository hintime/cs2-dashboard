# CS2 Dashboard 优化报告
生成时间: 2026-04-24

---

## 🔴 P0 — 必须修（Bug/风险）

### 1. `renderCandle` 函数体重复（merge conflict 遗留）
**位置**: `index.html` 第 ~1714-1742 行 和 ~1765-1793 行（两段完全相同的函数体）

`renderMarket()` 内部 `renderCandle()` 定义了两次，第二次会覆盖第一次。OPTIMIZATION_LOG 说已删除但实际还在。两次定义的 tooltip formatter 略有不同（'Index' vs '指数'）。

**修复**: 删除第二个 `renderCandle` 函数体，保留一份完整实现。

---

### 2. `id="pageSizeBar"` 重复了两次（未记录）
**位置**: `index.html` 第 ~390 行 和 ~403 行

两段完全相同的 HTML，都用了 `id="pageSizeSel"` 和 `id="pageSizeBar"`。第二个 select 永远无法被 `getElementById` 访问到，等于形同虚设。

**修复**: 删除其中一个。

---

### 3. `cost-overrides.json` 每次失焦都写盘（无 debounce）
**位置**: `index.html` 第 ~1168 行 `inp.onblur = save;`

用户连续修改多个成本价时，每次失焦都同步写文件。在机械硬盘或 I/O 受限时可能卡 UI。

**修复**: 改用 debounce（300ms）批量写。

---

## 🟡 P1 — 应该修（性能/健壮性）

### 4. `echarts.init` 未处理实例销毁
**位置**: `index.html` `ecInit()`

在 `renderLine/renderCandle` 切换时，`ec.setOption(..., true)` 会清空再重建，但不是真正的 `dispose`。连续切换 tab 时 ECharts 实例会累积。

**修复**: 在 `ecInit()` 前加 `ec?.dispose?.()`。

---

### 5. GitHub Actions commit 未检测数据是否真的变了
**位置**: `.github/workflows/update-all.yml`

`update.py` 即使什么都没更新（价格未变），也会 commit 一个空变更，用 `--allow-empty` 掩盖问题。长期造成大量无意义 commit。

**修复**: `update.py` 结束时 touch 一个标记文件，Workflow 检查是否有实质数据变化再决定是否 commit。

---

### 6. refresh 按钮已有 `isUpdating` 和 `btn.disabled = true` 保护 — 已 OK

---

### 7. `pageSizeSel` 绑定了两遍 `onchange`
**位置**: `index.html`

```js
DOM.pageSizeSel.onchange = function() { ... };       // 直接赋值
DOM.pageSizeSel.addEventListener('change', ...)       // addEventListener（少 invalidateCache）
```

`pageSizeSel` 的 change 事件会被执行两次。

**修复**: 保留有 `invalidateCache()` 的 addEventListener 版本，删除直接 .onchange 赋值。

---

### 8. `cost-overrides.json` 文件内容需确认
**文件**: `cost-overrides.json` 应为 `{}`。如果是其他值说明有 bug。

---

## 🟠 P2 — 可以修（工程化/长期）

### 9. `update.py` 和 `recommend.py` ECO 签名代码完全重复
两文件的 `get_eco_key()` / `sign_eco()` 实现一字不差。应提取为共享模块 `eco_sign.py`。

---

### 10. GitHub Actions 无版本 pinning
```yaml
uses: actions/setup-python@v5  # ✅ 有版本
run: pip install pycryptodome  # ❌ 无版本
```

`pycryptodome` 应指定 `pip install pycryptodome==3.20.0`，否则 minor 版本更新可能 break。

---

### 11. Workflow 两个脚本串行执行
`update.py`（holdings + market + recommendations）和 `index_collector.py`（指数）是独立的数据源，可以拆成两个并行 job，节省总运行时间。

---

### 12. `ecResizeTimer` 命名不明确
**位置**: `index.html`

`ecResizeTimer` 实际是 ECharts 的 resize 防抖 timer，但变量名没有体现是 `echarts` 专用。如果未来有其他 `setTimeout` 要统一管理，容易冲突。

---

### 13. GitHub Actions 日志泄露风险
`ECO_PRIVATE_KEY_B64` 虽然是 secret，但 `update.py` 里有 debug 输出显示 key 长度。建议删除所有 debug print。

**修复**: 删除 `update.py` 中以下行：
```python
print(f"[DEBUG] ECO_PRIVATE_KEY_B64 from env: ...")
print(f"[DEBUG] PEM header: ...")
print(f"[DEBUG] PEM length: ...")
print(f"[DEBUG] RSA import_key succeeded, ...")
```

---

### 14. 缺少数据备份机制
`market_history/` 单个快照最大 16MB（`2026-04-20_0100.json`），数据在 Git LFS 中没有备份。如果 Git 操作失败（如 `git reset --hard`），历史数据可能丢失。

---

### 15. CSS 重复定义（部分影响功能）
- `.sort-asc::after` / `.sort-desc::after` 定义了两次，第二次覆盖第一次丢失 `color:var(--blue)`，导致排序箭头变黑色
- `.loading-overlay` 定义了两次（重复）
- `.alert-card.supply` 定义了两次（重复）

---

## 📊 问题汇总

| 级别 | 数量 | 说明 |
|------|------|------|
| P0 | 3 | Bug/数据风险 |
| P1 | 5 | 性能/健壮性 |
| P2 | 7 | 工程化 |

**建议从 P0 开始修，尤其是 #1（重复函数体）和 #2（重复 ID），都是明确无误的问题。**
