const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf-8');
const start = html.indexOf('(function(){', 39000);
let depth = 0, inStr = false, inTmpl = false, strCh = '';
const script = html.substring(start);
let lastDepthChange = '';

for (let i = 0; i < script.length; i++) {
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
  
  const prevDepth = depth;
  if (ch === '{') depth++;
  if (ch === '}') depth--;
  
  // Track when depth goes to 1 and stays there (renderAnalysis area)
  // renderAnalysis starts around offset 79600 in script (2196 - 39735 + some margin)
  if (i > 75000 && depth === 1 && (ch === '{' || ch === '}')) {
    const line = script.substring(Math.max(0,i-30), Math.min(script.length,i+30)).replace(/\n/g, '\\n');
    console.log(`Offset ${i} (global ${start+i}): depth ${prevDepth}->${depth} char='${ch}' ctx: ${line}`);
  }
  
  if (depth === 0 && script.substring(i, i+4) === '})();') {
    console.log('IIFE close found at global', start+i);
    break;
  }
}
console.log('Final depth:', depth);
if (depth > 0) console.log('Missing', depth, 'closing braces');
