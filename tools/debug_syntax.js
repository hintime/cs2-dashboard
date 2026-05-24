const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf-8');

// Find the main IIFE start
const start = html.indexOf('(function(){', 39000);
console.log('IIFE start:', start);

// Walk through and find matching close
let depth = 0;
let inStr = false;
let inTmpl = false;
let strCh = '';
const script = html.substring(start);

for (let i = 0; i < script.length; i++) {
  const ch = script[i];
  const prev = i > 0 ? script[i-1] : '';
  
  if (!inTmpl && (ch === "'" || ch === '"') && prev !== '\\') {
    if (!inStr) { inStr = true; strCh = ch; }
    else if (ch === strCh) { inStr = false; }
    continue;
  }
  if (inStr) continue;
  
  if (ch === '`' && prev !== '\\') {
    inTmpl = !inTmpl;
    continue;
  }
  if (inTmpl) continue;
  
  if (ch === '{') depth++;
  if (ch === '}') depth--;
  
  if (depth === 0 && script.substring(i, i+4) === '})();') {
    console.log('IIFE closes at offset', i, 'global', start + i);
    const full = script.substring(0, i + 4);
    try { new Function(full); console.log('OK - syntax valid'); }
    catch(e) { console.log('ERROR:', e.message); }
    break;
  }
  
  if (depth < 0) {
    console.log('Depth went negative at offset', i);
    console.log('Context:', script.substring(Math.max(0,i-50), i+50));
    break;
  }
}
