[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
$env:CSQAQ_API_TOKEN = $env:CSQAQ_API_TOKEN
python update.py alerts 2>&1
