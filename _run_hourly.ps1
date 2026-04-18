# 静默后台运行，无窗口
Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
python update.py alerts 2>&1 | Out-Null
