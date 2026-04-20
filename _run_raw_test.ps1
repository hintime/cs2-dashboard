Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
Remove-Item _test_log.txt -ErrorAction SilentlyContinue
python _test_raw_bytes.py 2>&1
Get-Content _test_log.txt -Encoding UTF8
