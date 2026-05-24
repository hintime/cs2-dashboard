const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf-8');
const start = html.indexOf('(function(){', 39000);
let depth = 0, inStr = false, inTmpl = false, strCh = '';
const script = html.substring(start);
let maxDepth = 0;

for (let i = 0; i < Math.min(script.length, 100000); i++) {
  const ch = script[i];
  const prev = i > 0 ? script[i-1] : '';
  if (!inTmpl && (ch === "'" || ch === '"') && prev !== '\\') {
    if (!inStr) { inStr = true; strCh = ch; }
    else if (ch === strCh) { inStr = false; }
    continue;
  }
  if (inStr) continue;
  if (ch === '`' && prev !== '\\') { inTmpl = !inTmpl; continue; }
  if (inTmpl) continue;
  if (ch === '{') { depth++; if (depth > maxDepth) maxDepth = depth; }
  if (ch === '}') depth--;
}
console.log('Depth at 100k offset:', depth, 'max:', maxDepth);
if (depth !== 0) {
  console.log('Mismatch! Need to find', depth, 'more closing braces');
}
