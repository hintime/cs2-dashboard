[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$content = Get-Content 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\market.json' -Raw
Write-Host "=== First 50 lines ==="
$lines = $content -split "`n"
$lines[0..49] | ForEach-Object { Write-Host $_ }
