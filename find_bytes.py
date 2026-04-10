with open(r'C:\Users\Lenovo\cs2-dashboard\index.html', 'rb') as f:
    raw = f.read()

# Search for just '成交量' in UTF-8
target = '\u6210\u4ea4\u91cf'.encode('utf-8')  # 成交量的 UTF-8 bytes
idx = raw.find(target)
print(f"'成交量' UTF-8 at byte: {idx}")
print(repr(raw[idx-20:idx+120]))
