const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');

const lastScriptStart = c.lastIndexOf('<script>');
const lastScriptEnd = c.lastIndexOf('</script>');
const script = c.slice(lastScriptStart + 8, lastScriptEnd);

// Try to identify the error by looking for patterns
// Let's manually parse and find issues

// Check for common issues like unclosed parens/brackets
let parenDepth = 0;
let bracketDepth = 0;
let braceDepth = 0;
let inString = null;
let lineNum = 1;
let colNum = 1;
let errorPos = -1;

for (let i = 0; i < script.length; i++) {
  const char = script[i];
  
  if (char === '\n') {
    lineNum++;
    colNum = 1;
    continue;
  }
  
  // Handle string literals
  if (inString) {
    if (char === inString && script[i-1] !== '\\') {
      inString = null;
    }
    colNum++;
    continue;
  }
  
  if (char === '"' || char === "'" || char === '`') {
    inString = char;
    colNum++;
    continue;
  }
  
  // Track bracket depths
  if (char === '(') parenDepth++;
  else if (char === ')') parenDepth--;
  else if (char === '[') bracketDepth++;
  else if (char === ']') bracketDepth--;
  else if (char === '{') braceDepth++;
  else if (char === '}') braceDepth--;
  
  // Check for negative depth (unmatched closing)
  if (parenDepth < 0) {
    console.log(`Error at line ${lineNum}, col ${colNum}: Unexpected ')' - too many closing parens`);
    console.log('Context:', script.slice(Math.max(0, i-30), i+30));
    errorPos = i;
    break;
  }
  if (bracketDepth < 0) {
    console.log(`Error at line ${lineNum}, col ${colNum}: Unexpected ']' - too many closing brackets`);
    errorPos = i;
    break;
  }
  if (braceDepth < 0) {
    console.log(`Error at line ${lineNum}, col ${colNum}: Unexpected '}' - too many closing braces`);
    errorPos = i;
    break;
  }
  
  colNum++;
}

if (errorPos === -1) {
  console.log('No obvious bracket mismatch found');
  console.log('Final depths - parens:', parenDepth, 'brackets:', bracketDepth, 'braces:', braceDepth);
  
  // Let's look at the kline chart section more closely
  const klineStart = script.indexOf('klineEc.setOption');
  if (klineStart >= 0) {
    const klineSection = script.slice(klineStart, klineStart + 800);
    console.log('\\nK-line section sample:');
    console.log(klineSection.slice(-200));
  }
}