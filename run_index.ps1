$env:ECO_PRIVATE_KEY_B64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes("C:\Users\Lenovo\.qclaw\eco_private_key.pem"))
Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
python index_collector.py 2>&1
if ($LASTEXITCODE -eq 0) {
    git add market_history/ market.json index_history/
    git commit -m "chore: auto index $(Get-Date -Format 'yyyy-MM-dd HH:mm')" --allow-empty
    git push 2>&1
}
