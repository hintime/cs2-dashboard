const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');

// Extract the inline script
const lastScriptStart = c.lastIndexOf('<script>');
const lastScriptEnd = c.lastIndexOf('</script>');
const script = c.slice(lastScriptStart + 8, lastScriptEnd);

const lines = script.split('\n');
const line257Offset = lastScriptStart + 8; // offset in file for line 257

// Browser reports error at line 541 → that's line 541-257 = 284 in the script
const browserLine = 541;
const scriptLine = browserLine - 257;

console.log('File <script> starts at char offset:', lastScriptStart);
console.log('Script total lines:', lines.length);
console.log('Script line 284 (browser line 541):');
console.log(lines[scriptLine]);

// Check surrounding lines
console.log('\n--- Context around line 284 ---');
for (let i = Math.max(0, scriptLine - 5); i < Math.min(lines.length, scriptLine + 5); i++) {
  console.log(`  Script[${i}] (file ${i + 257}): ${lines[i].slice(0, 100)}`);
}

// Parse and validate JavaScript syntax
try {
  new Function(script);
  console.log('\nJavaScript syntax OK');
} catch (e) {
  console.log('\nSYNTAX ERROR:', e.message);
  
  // Try to find the error position
  if (e.message.includes('Unexpected token')) {
    const match = e.message.match(/at position (\d+)/);
    if (match) {
      const pos = parseInt(match[1]);
      const filePos = line257Offset + pos;
      console.log(`Error at script char ${pos} = file char ${filePos}`);
      console.log(`Context: ...${script.slice(Math.max(0, pos-30), pos+30)}...`);
    }
  }
}
