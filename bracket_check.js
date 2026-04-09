const fs = require('fs');
const c = fs.readFileSync('C:/Users/Lenovo/cs2-dashboard/index.html', 'utf8');
const script = c.slice(c.lastIndexOf('<script>') + 8, c.lastIndexOf('<\/script>'));
const lines = script.split('\n');

function countBr(s) {
  return {
    o: (s.match(/\{/g)||[]).length,
    c: (s.match(/\}/g)||[]).length,
    ob: (s.match(/\[/g)||[]).length,
    cb: (s.match(/\]/g)||[]).length
  };
}

for (let i = 265; i <= 290; i++) {
  if (!lines[i]) continue;
  const b = countBr(lines[i]);
  const net = b.o - b.c;
  const bnet = b.ob - b.cb;
  const info = net === 0 && bnet === 0 ? '' : ' <--';
  console.log('SL' + (i+1) + ' HB' + (i+258) + ' {net:' + net + '} [net:' + bnet + ']' + info);
  console.log('    ' + lines[i].slice(0, 100));
}
