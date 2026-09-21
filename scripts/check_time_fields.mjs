#!/usr/bin/env node
/**
 * check_time_fields.mjs —— 时间字段口径检查（2026-09-21 新增）
 *
 * 背景：status.html / index.html 先后两次犯同一错误 —— 取值链里把
 * alerts_updated / market_updated（6 小时一轮的 all 写入）排在
 * updated（每 30 分钟 prices 写入）前面，导致页面显示的时间最多滞后 6 小时。
 *
 * 规则：同一行内若同时出现 `.updated` 与（alerts_updated|market_updated|
 * update_time|items_updated），则 .updated 必须排在最前（|| 链的第一个）。
 * 违反 → 退出码 1，CI 拦截。
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = process.cwd();
const files = readdirSync(ROOT).filter(f => f.endsWith('.html'));
let bad = 0;
for (const f of files) {
  const lines = readFileSync(join(ROOT, f), 'utf-8').split('\n');
  lines.forEach((line, i) => {
    if (!line.includes('alerts_updated') && !line.includes('market_updated') &&
        !line.includes('update_time') && !line.includes('items_updated')) return;
    if (!line.includes('.updated')) return;
    const iUpdated = line.indexOf('.updated');
    for (const fld of ['alerts_updated', 'market_updated', 'update_time', 'items_updated']) {
      const i = line.indexOf(fld);
      if (i !== -1 && i < iUpdated) {
        console.error(`X ${f}:${i + 1} —— ${fld} 排在 .updated 之前（会导致页面时间滞后）：`);
        console.error(`    ${line.trim().slice(0, 130)}`);
        bad++;
      }
    }
  });
}
if (bad) {
  console.error(`\n共 ${bad} 处口径错误。取值链必须 .updated 优先（每 30 分钟 prices 刷新）。`);
  process.exit(1);
}
console.log('OK 时间字段口径检查通过（updated 均在取值链首位）');
