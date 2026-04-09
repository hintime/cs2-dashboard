const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const script = c.slice(c.lastIndexOf('<script>') + 8, c.lastIndexOf('<\/script>'));
const lines = script.split('\n');

// Extract lines 274-290 (setOption block) and test each line incrementally
for (let end = 274; end <= 290; end++) {
  const test = lines.slice(273, end + 1).join('\n');
  try {
    new Function(test);
    console.log('Lines 274-' + (end+1) + ': OK');
  } catch (e) {
    console.log('Lines 274-' + (end+1) + ': FAIL - ' + e.message);
    const ctx = lines.slice(Math.max(273, end-2), end+1);
    ctx.forEach((l, i) => console.log('  ' + l.slice(0,120)));
    break;
  }
}
