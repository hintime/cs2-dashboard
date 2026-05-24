const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf-8');
const start = html.indexOf('(function(){', 39000);
const script = html.substring(start);
let inTmpl = false;
let tmplStarts = [];
let tmplEnds = [];
for (let i = 0; i < Math.min(script.length, 90000); i++) {
  const ch = script[i];
  const prev = i > 0 ? script[i-1] : '';
  if (ch === '`' && prev !== '\\') {
    inTmpl = !inTmpl;
    if (inTmpl) tmplStarts.push(i);
    else tmplEnds.push(i);
  }
}
console.log('Template opens:', tmplStarts.length, 'closes:', tmplEnds.length);
if (tmplStarts.length !== tmplEnds.length) {
  console.log('UNCLOSED TEMPLATE! Last open at offset', tmplStarts[tmplStarts.length-1]);
  const pos = tmplStarts[tmplStarts.length-1];
  console.log('Context:', script.substring(pos, pos+600));
}
