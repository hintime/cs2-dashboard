const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
// Find the inline script (between the last <script> and </script>)
const lastScriptStart = c.lastIndexOf('<script>');
const lastScriptEnd = c.lastIndexOf('</script>');

if (lastScriptStart >= 0 && lastScriptEnd > lastScriptStart) {
  const script = c.slice(lastScriptStart + 8, lastScriptEnd);
  console.log('Inline script length:', script.length);
  console.log('First 100 chars:', script.slice(0, 100));
  console.log('Last 100 chars:', script.slice(-100));
  
  try {
    new Function(script);
    console.log('JavaScript syntax is valid');
  } catch (e) {
    console.log('Syntax error:', e.message);
    console.log('Position:', e.position);
  }
} else {
  console.log('No inline script found');
}