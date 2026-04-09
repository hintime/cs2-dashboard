const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
// Find the LAST </script> tag properly (handle \r\n)
const si = c.lastIndexOf('<script>');
const se = c.lastIndexOf('</script>');
const script = c.slice(si + 8, se);
fs.writeFileSync('C:/Users/Lenovo/cs2-dashboard/temp_check.js', script);
console.log('Script length:', script.length, 'chars');
console.log('First 50 chars:', JSON.stringify(script.slice(0,50)));
console.log('Last 30 chars:', JSON.stringify(script.slice(-30)));
