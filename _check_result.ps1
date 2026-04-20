[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$j = Get-Content 'market.json' | ConvertFrom-Json
Write-Host "alerts count:" $j.alerts.Count
if ($j.alerts.Count -gt 0) {
    $a = $j.alerts[0]
    Write-Host "First alert name:" $a.name
    Write-Host "First alert exterior:" $a.exterior
}
Write-Host ""
Write-Host "index.latest:" $j.index.latest
Write-Host "index.change_pct:" $j.index.change_pct
