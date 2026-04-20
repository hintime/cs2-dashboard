[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$r = Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/hintime/cs2-dashboard/main/market.json' -UseBasicParsing
$json = $r.Content | ConvertFrom-Json
Write-Host "index_updated:" $json.index.updated
Write-Host "selling_stats:" ($json.selling_stats | ConvertTo-Json -Compress)
