with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'rb') as f:
    raw = f.read()

# Fix K线 corruption
old1 = b"name:'K\xe7\xba\xbf',data:kl.map(k=>[k[1],k[2],k[3],k[4]]),xAxisIndex:0,yAxisIndex:0"
new1 = b"name:'MA',data:kl.map(k=>[k[1],k[2],k[3],k[4]]),xAxisIndex:0,yAxisIndex:0"
idx1 = raw.find(old1)
print(f"K线 at {idx1}")

# Fix MA10 name corruption (MA10 → 10日线)
old2 = b"name:'MA10',data:ma10"
new2 = b"name:'MA10',data:ma10"
idx2 = raw.find(old2)
print(f"MA10 at {idx2}")
print(repr(raw[idx2-20:idx2+40]))

if idx1 != -1:
    raw = raw[:idx1] + new1 + raw[idx1+len(old1):]
    
with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'wb') as f2:
    f2.write(raw)
print("Done!")
