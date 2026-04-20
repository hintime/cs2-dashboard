[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$r = Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/hintime/cs2-dashboard/main/market.json' -UseBasicParsing
$json = $r.Content | ConvertFrom-Json
Write-Host "=== Top-level keys ==="
$json.PSObject.Properties | ForEach-Object { Write-Host $_.Name }
Write-Host ""
Write-Host "=== index object ==="
$json.index | ConvertTo-Json -Depth 2
