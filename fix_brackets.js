const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const script = c.slice(c.lastIndexOf('<script>') + 8, c.lastIndexOf('<\/script>'));
const lines = script.split('\n');

// Fix lines 284-286:
// Current:
// 284: ...}]}   (markPoint行，ends with }]})
// 285:     }]}   (extra line, bad)
// 286:   });     (ec.setOption closing)

// Should be:
// 284: ...}]}   (markPoint行，保持)
// 286:   ]});    (close series[], close options{}, close setOption call)
// (delete line 285 entirely)

lines[284] = lines[284].trimEnd(); // remove trailing \r from markPoint line
lines.splice(285, 1); // remove the extra line
lines[284] = lines[284].replace(/\}\}$/, '}]}'); // ensure ends with }]}
// line 285 now (was 286): change '  });' to '    ]});'
lines[285] = '    ]});';

const newScript = lines.join('\r\n');
const newHtml = c.slice(0, c.lastIndexOf('<script>') + 8) + newScript + c.slice(c.lastIndexOf('<\/script>'));
fs.writeFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', newHtml);
console.log('Fixed. Line 284:', JSON.stringify(lines[283]));
console.log('Line 285:', JSON.stringify(lines[284]));
console.log('Line 286:', JSON.stringify(lines[285]));
