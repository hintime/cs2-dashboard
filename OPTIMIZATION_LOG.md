# CS2 饰品投资看板 · 优化记录

## 2026-04-24 凌晨 (完成)

### 已推送提交
- `e4ab688`: Merge holdings.json + market.json update (远程数据)
- `6773b8f`: **DocumentFragment for analysis-cards** — `container.innerHTML = analyses.map(...).join('')` → `createDocumentFragment` + `forEach` + `appendChild`，31 行模板字符串替换为 27 行 DOM 构建
- `ffa8d24`: fix: remove duplicate csvBtn element
- `e0b82b4`: docs: add optimization log
- `980c260`: perf-tech-indicator-cache
- `58ae4c9`: perf-lazy-echarts-init-search-debounce

### 优化详情

#### 1. ECharts 懒加载初始化 (58ae4c9)
**问题**：页面加载时立即调用 `echarts.init(DOM.indexChart)`，但大盘指数图表只有用户点击"折线图/K线图" tab 时才需要。

**修复**：
- `ecInit()` 函数在用户首次点击图表 tab 时才创建 ECharts 实例
- `ecResizeTimer` + `setTimeout` 替代 `cancelAnimationFrame/requestAnimationFrame`
- 移除 `initChart()` 自动调用，避免刷新时重复初始化

#### 2. 搜索防抖 200ms → 150ms (58ae4c9)
更快响应输入，配合缓存键中的 `searchQuery`。

#### 3. 技术指标缓存 (980c260)
`techFor(item)` + `_techCache` 避免 `renderAnalysis()` 中重复计算 MA/布林带/均线结构。

#### 4. DocumentFragment for analysis-cards (6773b8f)
`container.innerHTML = analyses.map(...).join('')` 替换为 `createDocumentFragment` + `forEach` + `appendChild`：
- 减少 N 次 DOM 写入为 1 次
- 减少 1 次 `innerHTML` 重解析
- 降低浏览器重排/重绘次数

#### 5. 修复重复 csvBtn (ffa8d24)
DOM 中两个相同 `id="csvBtn"` 已删除多余元素。

---

## 待处理
- Skeleton loading：数据加载时缺少骨架屏过渡
- `updatePhase` 多阶段刷新状态变量未实际使用（可删除）
- `alertsGrid` / `recGrid` 已有 DocumentFragment（无需改）
- `renderAlertsTab` / `renderRecTab` 已有 DocumentFragment（无需改）
- `render()` 持仓表格已有 DocumentFragment（无需改）

## 项目概况
- 仓库：hintime/cs2-dashboard（GitHub Pages 静态站）
- 技术栈：单文件 HTML + CSS + JS + ECharts 5.5.0
- 最新提交：e4ab688 (main)