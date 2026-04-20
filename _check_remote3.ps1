[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$r = Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/hintime/cs2-dashboard/main/market.json' -UseBasicParsing
$json = $r.Content | ConvertFrom-Json
Write-Host "index_updated:" $json.index_updated
Write-Host "alerts_updated:" $json.alerts_updated
Write-Host "items_updated:" $json.items_updated
Write-Host ""
Write-Host "=== index.ohlc count ===" $json.index.ohlc.Count
Write-Host "=== index.series count ===" $json.index.series.Count
