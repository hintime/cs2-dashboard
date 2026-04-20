[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$content = Get-Content 'market.json' -Raw
Write-Host "=== First 800 chars ==="
Write-Host $content.Substring(0, 800)
Write-Host ""
Write-Host "=== alerts sample ==="
if ($content -match '"alerts"') {
    Write-Host "alerts field exists"
    $json = $content | ConvertFrom-Json
    Write-Host "alerts count:" $json.alerts.Count
    if ($json.alerts.Count -gt 0) {
        $a = $json.alerts[0]
        Write-Host "First alert name:" $a.name
    }
}
