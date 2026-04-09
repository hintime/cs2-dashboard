const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');

const lastScriptStart = c.lastIndexOf('<script>');
const lastScriptEnd = c.lastIndexOf('</script>');
const script = c.slice(lastScriptStart + 8, lastScriptEnd);

// Check first 50 lines for any initialization issues
const lines = script.split('\n');
console.log('First 20 lines:');
for (let i = 0; i < 20; i++) {
  console.log(`${i+1}: ${lines[i].slice(0,80)}`);
}

// Let's also look at how the script starts (the (function(){ part)
console.log('\n=== Script starts with ===');
console.log(script.slice(0, 100));