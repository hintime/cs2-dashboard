with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'rb') as f:
    raw = f.read()

old = b"  {type:'bar',name:'\xe6\x88\x90\xe4\xba\xa4\xe9\x87\x8f',data:volumes,xAxisIndex:1,yAxisIndex:1,itemStyle:{color:kl.map(k=>k[2]>=k[1]?'#ef444433':'#22c55e33'})}"
new = b"  {type:'bar',name:'Volume',data:volumes,xAxisIndex:1,yAxisIndex:1,itemStyle:{color:volColors}}"

idx = raw.find(old)
if idx == -1:
    print("Not found! Trying partial search...")
    # Find the volumes part
    part = b"volumes,xAxisIndex:1,yAxisIndex:1,itemStyle:{color:kl.map"
    p2 = raw.find(part)
    print(f"Partial pattern at: {p2}")
    print(repr(raw[p2-60:p2+200]))
else:
    fixed = raw[:idx] + new + raw[idx+len(old):]
    with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'wb') as f2:
        f2.write(fixed)
    print(f"Fixed at byte {idx}!")
