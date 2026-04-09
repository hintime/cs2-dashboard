// Use node --check to validate syntax
const { execSync } = require('child_process');
const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const script = c.slice(c.lastIndexOf('<script>') + 8, c.lastIndexOf('<\/script>'));

// Write to temp file
fs.writeFileSync('C:/Users/Lenovo/cs2-dashboard/temp_check.js', script);
console.log('Written temp_check.js');

try {
  execSync('node --check C:/Users/Lenovo/cs2-dashboard/temp_check.js', {encoding: 'utf8'});
  console.log('SYNTAX OK');
} catch (e) {
  console.log('STDERR:', e.stderr);
}
