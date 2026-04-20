Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
python _verify.py 2>&1
Get-Content _verify_result.txt -Encoding UTF8
