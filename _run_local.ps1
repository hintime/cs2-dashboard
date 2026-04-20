Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
$env:ECO_PRIVATE_KEY_B64 = $env:ECO_PRIVATE_KEY_B64
python index_collector.py 2>&1
