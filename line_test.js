const fs = require('fs');
const vm = require('vm');

const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const script = c.slice(c.lastIndexOf('<script>') + 8, c.lastIndexOf('<\/script>'));
const lines = script.split('\n');

// Try to compile line by line
for (let i = 273; i <= 290; i++) {
  const snippet = lines.slice(273, i + 1).join('\n');
  try {
    new vm.Script(snippet, { filename: 'inline.js', produceCachedData: false });
    // Check with Function too since vm.Script doesn't catch all errors
  } catch (_) {}
  try {
    new Function(snippet);
  } catch (e) {
    console.log('FAILS at line SL' + (i+1) + ' (HB' + (i+258) + '): ' + e.message);
    break;
  }
}
console.log('OK through line SL290');
