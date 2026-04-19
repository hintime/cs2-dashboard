# 任务：持仓分析可信度修复

## 问题诊断

**现象**：持仓分析里所有饰品显示"🔴 低可信度"

**根因**：
1. `holdings.json` 存储用户持仓（32件），含 `market_hash`（英文Steam名）
2. `market.json` 的 `alerts`（71件）来自 CSQAQ 涨跌榜，只有中文名
3. 用户持仓多为冷门/稀有品（Commemorative、Moss Quartz、Polysoup等），不在 CSQAQ 追踪范围
4. **零匹配**：持仓 ↔ alerts 按名称匹配 = 0 件
5. 前端 `renderAnalysis()` 从 alerts 匹配 rate 数据 → 全部失败 → 可信度默认"低"

## 解决方案

**长期方案**：持仓自带涨跌数据，不再依赖 alerts 匹配

### 后端修改 (update.py)

在 `prices` 模式下新增：
```python
# 记录历史价格（用于计算涨跌率）
history = item.get('price_history', [])
history.append({'date': today, 'price': new_price})
item['price_history'] = history[-60:]  # 保留最近60天

# 计算 rate_1：相对上次更新的涨跌
if old_price > 0:
    item['rate_1'] = round((new_price - old_price) / old_price * 100, 2)

# 计算 rate_7/rate_30：相对7天前/30天前的涨跌（需要历史数据积累）
```

### 前端修改 (index.html)

1. **数据加载**：`H` 数组传递 `rate_1`/`rate_7`/`rate_30`/`price_history` 字段
2. **renderAnalysis()**：优先使用持仓自带的 rate 数据，fallback 到 alerts 匹配
```javascript
const r1 = item.rate_1 !== undefined ? item.rate_1 : (rateMap[name]?.r1 || 0);
```

## 效果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| rate_1 覆盖 | 0/32 件 | 32/32 件 |
| 可信度判断 | 全部"低" | 根据涨跌幅度动态计算 |
| rate_7 覆盖 | 0/32 件 | 需7天数据积累 |
| rate_30 覆盖 | 0/32 件 | 需30天数据积累 |

## 提交记录

- `9fd8a9e`: feat: holdings自带rate_1/rate_7数据 + 前端使用持仓rate
- `a5a03db`: chore: update holdings.json 2026-04-19 16:01

## 后续

1. 等待定时任务每小时运行，积累历史数据
2. 7天后 rate_7 开始有数据
3. 30天后 rate_30 开始有数据
4. 可考虑从 ECO API 获取更多历史数据（如果有提供）

---

时间：2026-04-19 16:02
