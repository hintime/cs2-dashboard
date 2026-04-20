[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$j = Get-Content 'market.json' | ConvertFrom-Json
Write-Host "index.latest:" $j.index.latest
Write-Host "index.change_pct:" $j.index.change_pct
Write-Host "ohlc count:" $j.index.ohlc.Count
Write-Host "series count:" $j.index.series.Count
Write-Host "trending hot:" $j.index.trending.hot.Count
Write-Host "trending cold:" $j.index.trending.cold.Count
