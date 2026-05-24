# Cloudflare Workers 部署指南

## 1. 创建 Worker

1. 打开 https://dash.cloudflare.com → Workers 和 Pages
2. 点「创建应用程序」→「创建 Worker」
3. 名称填 `cs2-dashboard-api`
4. 把 `worker.js` 的内容复制粘贴到编辑器中 → 点「部署」

## 2. 设置环境变量

5. 回到 Worker 详情 → 设置 → 变量
6. 添加环境变量：
   - `CSQ_API_TOKEN` = 你的 CSQAQ Token

## 3. 获取 Worker 地址

7. Workers 和 Pages 列表页，找到你的 Worker
8. 地址类似：`https://cs2-dashboard-api.xxx.workers.dev`
9. 测试：`https://cs2-dashboard-api.xxx.workers.dev/api/ping`

## 至此完成

部署后你有了：
- `/api/csqaq/batch?names=AK-47+Redline,AWP+Asiimov` — 实时查价（隐藏了 API token）
- `/api/csqaq/alerts` — 排行榜
- `/api/gh/market.json` — GitHub 文件加速（Cloudflare 边缘缓存）

前端改造后续再做，先确认 API 能通。
