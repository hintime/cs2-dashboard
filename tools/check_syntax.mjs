import fs from 'fs';
const html = fs.readFileSync('index.html', 'utf-8');

// Extract the main IIFE script
const start = html.indexOf('(function(){');
let depth = 0;
let inTemplate = false;
let inString = false;
let strChar = '';
let minDepth = 0;

for (let i = start; i < html.length; i++) {
    const ch = html[i];
    const prev = i > 0 ? html[i - 1] : '';
    
    if (ch === '`' && prev !== '\\') {
        inTemplate = !inTemplate;
        continue;
    }
    
    if (!inTemplate) {
        if ((ch === "'" || ch === '"') && prev !== '\\') {
            if (!inString) { inString = true; strChar = ch; }
            else if (ch === strChar) { inString = false; }
            continue;
        }
    }
    if (inString) continue;
    
    if (!inTemplate) {
        if (ch === '{') depth++;
        if (ch === '}') depth--;
        if (depth < minDepth) minDepth = depth;
    }
    
    if (depth === 0 && ch === ')' && html.substring(i, i + 4) === '})();') {
        console.log('IIFE closes at position', i);
        console.log('Current depth:', depth);
        console.log('Min depth:', minDepth);
        break;
    }
}

console.log('Final depth:', depth);

// Try to compile the script
const script = html.substring(start, html.indexOf('})();', start) + 4);
try {
    new Function(script);
    console.log('Script syntax: OK');
} catch(e) {
    console.log('Script syntax ERROR:', e.message);
}
