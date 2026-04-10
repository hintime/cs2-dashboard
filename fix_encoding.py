# -*- coding: utf-8 -*-
import os, re

os.chdir(r'C:\Users\Lenovo\cs2-dashboard')

# Read the file
with open('index.html', 'rb') as f:
    data = f.read()

# The corrupted bytes appear to be:
# 楂 (should be 高) = \xe9\xab\x98 in GBK but damaged
# 浣 (should be 低) = \xe4\xbd\x8e in GBK but damaged

# Let's try to find and fix the specific pattern
# by looking at the hex values

# First, let's see what we have around markPoint
idx = data.find(b'markPoint')
if idx > 0:
    print(f"Found markPoint at {idx}")
    snippet = data[idx:idx+200]
    print(f"Snippet (hex): {snippet[:100].hex()}")
    print(f"Snippet (repr): {repr(snippet[:100])}")
