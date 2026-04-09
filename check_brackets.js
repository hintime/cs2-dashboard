const fs = require('fs');
const html = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (scriptMatch) {
  const script = scriptMatch[1];
  // Split by lines and check from line 555 onwards (around kline section)
  const lines = script.split('\n');
  console.log('Total lines:', lines.length);
  
  // Check lines around 555-580 (kline section)
  for (let i = 555; i < Math.min(580, lines.length); i++) {
    const line = lines[i];
    const opens = (line.match(/\(/g) || []).length;
    const closes = (line.match(/\)/g) || []).length;
    if (opens !== closes) {
      console.log(`Line ${i+1}: opens=${opens} closes=${closes}`);
      console.log('  ', line.slice(0,100));
    }
  }
}