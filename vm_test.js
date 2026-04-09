const fs = require('fs');
const vm = require('vm');

const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const lastScriptStart = c.lastIndexOf('<script>');
const lastScriptEnd = c.lastIndexOf('</script>');
const script = c.slice(lastScriptStart + 8, lastScriptEnd);

try {
  new vm.Script(script, { filename: 'inline.js' });
  console.log('Script compiles OK');
} catch (e) {
  console.log('Error:', e.message);
  if (e.stack) {
    // Extract the line number from the stack
    const match = e.stack.match(/inline\.js:(\d+)/);
    if (match) {
      const lineNum = parseInt(match[1]);
      const lines = script.split('\n');
      const start = Math.max(0, lineNum - 3);
      const end = Math.min(lines.length, lineNum + 2);
      for (let j = start; j < end; j++) {
        console.log(`${j + 1}: ${lines[j].slice(0, 120)}`);
      }
    }
  }
}
