const fs = require('fs');
const html = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (scriptMatch) {
  try {
    new Function(scriptMatch[1]);
    console.log('JavaScript syntax is valid');
  } catch (e) {
    console.log('Syntax error:', e.message);
    console.log('At line:', e.lineNumber);
  }
}