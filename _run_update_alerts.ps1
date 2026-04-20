Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:CSQ_API_TOKEN = "HXGPY1R7L5W7K7F3O4K1E2N8"
python update.py alerts 2>&1
