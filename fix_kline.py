import re

with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the bad volume bar line
# Look for the kl.map ternary inside series
old = "{type:'bar',name:'\u00d8\u00b7\u00ea\u00d0\u00b1\u00ec\u00df',data:volumes,xAxisIndex:1,yAxisIndex:1,itemStyle:{color:kl.map(k=>k[2]>=k[1]?'#ef444433':'#22c55e33')}}"

# Try to find it with raw bytes
with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'rb') as f:
    raw = f.read()

# Search for 'bar' that comes after 'xAxisIndex'
# Find "xAxisIndex:1,yAxisIndex:1,itemStyle:{color:kl.map"
search = b"xAxisIndex:1,yAxisIndex:1,itemStyle:{color:kl.map(k=>k[2]>=k[1]?'#ef444433':'#22c55e33')"
idx = raw.find(search)
if idx == -1:
    print("Pattern not found in raw bytes")
    # Try simpler search
    idx2 = raw.find(b"volumes,xAxisIndex:1")
    print(f"volumes,xAxisIndex:1 at {idx2}")
    print(repr(raw[idx2-20:idx2+200]))
else:
    print(f"Found at byte {idx}")
    print(repr(raw[idx-50:idx+250]))
    # Replace with fixed version
    new_line = b"{type:'bar',name:'Volume',data:volumes,xAxisIndex:1,yAxisIndex:1,itemStyle:{color:volColors}}"
    fixed = raw[:idx] + new_line + raw[idx+len(search):]
    with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'wb') as f2:
        f2.write(fixed)
    print("Fixed!")
