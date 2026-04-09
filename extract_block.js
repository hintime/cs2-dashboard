// Extract and verify just the setOption block
const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const script = c.slice(c.lastIndexOf('<script>') + 8, c.lastIndexOf('<\/script>'));
const lines = script.split('\n');

// Extract lines 274-287 (ec.setOption block) - inclusive
const block = lines.slice(273, 287).join('\n');
console.log('Block lines:');
console.log(block);
console.log('\n---\n');

fs.writeFileSync('C:/Users/Lenovo/cs2-dashboard/setoption_test.js', block);
console.log('Written. Now checking...');
