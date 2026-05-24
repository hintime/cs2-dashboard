const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf-8');

// Find the main IIFE script block
const scriptStart = html.indexOf('<script>', 39000);
const scriptEnd = html.indexOf('</script>', scriptStart);
const rawScript = html.substring(scriptStart + 8, scriptEnd);

try {
  new Function(rawScript);
  console.log('SCRIPT OK');
} catch(e) {
  console.log('SCRIPT ERROR:', e.message);
  const m = e.message.match(/position (\d+)/);
  if (m) {
    const pos = parseInt(m[1]);
    console.log('Context:', rawScript.substring(Math.max(0,pos-80), pos+80));
  }
}
