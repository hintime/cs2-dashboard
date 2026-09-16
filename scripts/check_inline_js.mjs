// 检查所有 HTML 的内联 <script> 语法（用 vm.Script 编译，不执行）
// 用法: node tools/check_inline_js.mjs
// 退出码: 0=全部正常  1=有语法错误
import fs from 'node:fs';
import { Script } from 'node:vm';

const files = fs.readdirSync('.').filter(f => f.endsWith('.html'));
let fail = 0;
let checked = 0;

for (const f of files) {
  const lines = fs.readFileSync(f, 'utf8').split(/\r?\n/);
  let inScript = false;
  let buf = [];
  let startLine = 0;

  const flush = (endLine) => {
    if (!inScript) return;
    const src = buf.join('\n');
    if (src.trim()) {
      checked++;
      try {
        new Script(src);          // 只编译不执行 —— 语法错误会抛出
      } catch (e) {
        fail++;
        console.log(`[FAIL] ${f}: 内联 JS（行 ${startLine + 1}-${endLine}）语法错误: ${e.message}`);
      }
    }
    inScript = false;
    buf = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!inScript && /<script(\s[^>]*)?>/.test(line)) {
      if (/src\s*=/.test(line)) {           // 外链脚本，跳过
        // 但同一行如果有内联内容也忽略（本站没有这种写法）
        continue;
      }
      inScript = true;
      buf = [];
      startLine = i;
      const rest = line.replace(/^[\s\S]*?<script[^>]*>/, '');
      if (rest.trim()) buf.push(rest);
      continue;
    }
    if (inScript && /<\/script\s*>/.test(line)) {
      const pre = line.replace(/<\/script\s*>[\s\S]*$/, '');
      if (pre.trim()) buf.push(pre);
      flush(i + 1);
      continue;
    }
    if (inScript) buf.push(line);
  }
  flush(lines.length);
}

if (fail) {
  console.log(`\n${fail} 个内联 JS 语法错误（共检查 ${checked} 块）`);
  process.exit(1);
}
console.log(`✔ ${files.length} 个 HTML、${checked} 块内联 JS 语法全部正常`);
