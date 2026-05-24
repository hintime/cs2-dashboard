const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf-8');
const start = html.indexOf('(function(){', 39000);
const script = html.substring(start);

let depth = 0;
let inStr = false;
let inTmpl = false;
let strChar = '';

for (let i = 0; i < script.length; i++) {
  const ch = script[i];
  const prev = i > 0 ? script[i-1] : '';

  // Track template literals
  if (ch === '`' && prev !== '\\') {
    inTmpl = !inTmpl;
    continue;
  }
  if (inTmpl) continue;

  // Track strings
  if ((ch === "'" || ch === '"') && prev !== '\\') {
    if (!inStr) { inStr = true; strChar = ch; }
    else if (ch === strChar) { inStr = false; }
    continue;
  }
  if (inStr) continue;

  if (ch === '{') depth++;
  if (ch === '}') depth--;

  if (depth === 0 && script.substring(i, i+4) === '})();') {
    console.log('IIFE close at', start + i);
    console.log('Script syntax OK');
    try {
      new Function(script.substring(0, i+4));
      console.log('Function compiles OK');
    } catch(e) {
      console.log('Function ERROR:', e.message);
    }
    break;
  }
}
if (depth !== 0) {
  console.log('Final depth:', depth, '- IIFE never closes!');
  // Find where depth goes wrong
}
