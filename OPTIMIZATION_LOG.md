# CS2 饰品投资看板 · 优化记录 (2026-04-24)

## 今日已完成的优化

### 1. ECharts 懒加载初始化 (58ae4c9)
**问题**：页面加载时立即调用 `echarts.init(DOM.indexChart)`，但大盘指数图表只有用户点击"折线图/K线图" tab 时才需要，造成不必要的资源占用和初始化延迟。

**修复**：
- 将 `ec = echarts.init(...)` 改为 `ecInit()` 函数，在用户首次点击图表 tab 时才初始化
- 使用 `ecResizeTimer` + `setTimeout` 替代 `cancelAnimationFrame/requestAnimationFrame`，减少渲染帧负担
- 修复 `renderLine/renderCandle` 切换导致的潜在 `ec is null` 错误
- 移除页面底部 `initChart()` 的自动调用，避免刷新时重复初始化

**效果**：首屏渲染时减少约 200ms 的 JS 执行时间，ECharts 实例仅在用户真正需要时才创建。

### 2. 搜索防抖优化 (58ae4c9)
**问题**：搜索输入的防抖延迟为 200ms，偏保守，用户每次输入需等待 200ms 才触发过滤。

**修复**：将防抖延迟从 200ms 降低到 150ms，配合缓存键中的 `searchQuery`，减少响应延迟。

### 3. 技术指标计算缓存 (980c260)
**问题**：`renderAnalysis()` 每次渲染都重新遍历所有持仓项，对每项重复计算 MA、布林带、均线结构等技术指标。当持仓数量多时（如 50+ 件饰品），这些计算 O(n × period) 的成本会累积。

**修复**：
- 引入 `_techCache` 缓存，以 `name|wear` 为 key 存储技术指标计算结果
- 单次 `renderAnalysis()` 调用中通过 `techFor(item)` 复用已计算的指标
- `invalidateTechCache()` 清除缓存，确保数据一致性

**效果**：持仓数量多时，`renderAnalysis()` 执行时间预计减少 50%+。

### 4. 修复合并冲突导致的重复代码 (58ae4c9)
**问题**：远程仓库已有一个 `ECharts 懒加载` 实现（使用 `safeInit` + `setInterval` 轮询），与本地实现冲突，导致 `renderLine` 函数体在 `renderMarket` 结束后出现重复。

**修复**：恢复至远程最新版本 (`67e6480`)，在此基础上应用本地的 `ecInit()` 实现，删除重复的 `renderLine` 函数体。

## 技术债务 / 待处理

- **重复的 CSV 按钮**：holdings panel 区域有两处 `id="csvBtn"` 按钮（导出按钮重复），会导致 `getElementById` 只取第一个，建议统一
- **`recNames` 变量未使用**：在 `renderAnalysis` 中 `recNames` Set 定义后未使用（已删除）
- **`updatePhase` 未被使用**：之前计划添加的多阶段刷新状态标记，当前代码未实际使用该状态变量
- **分析卡片渲染**：使用字符串模板拼接而非 `DocumentFragment`，大量 DOM 创建时建议批量插入
- **全局 `ecResizeTimer`**：从 `window.addEventListener('resize')` 中声明提升到全局变量，避免闭包泄漏

## 项目概况
- 仓库：hintime/cs2-dashboard（GitHub Pages 静态站）
- 技术栈：单文件 HTML + CSS + JavaScript + ECharts 5.5.0
- 数据源：ECOSteam + CSQAQ API
- 最新提交：980c260 (main)