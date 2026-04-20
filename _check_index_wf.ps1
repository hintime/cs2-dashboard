Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$token = Get-Content .env -Raw | Select-String 'GH_TOKEN=(.+)' | ForEach-Object { $_.Matches.Groups[1].Value.Trim() }
if (-not $token) { $token = $env:GH_TOKEN }

$headers = @{
    'Authorization' = "token $token"
    'Accept' = 'application/vnd.github.v3+json'
}

# Check update-index workflow runs
$url = 'https://api.github.com/repos/hintime/cs2-dashboard/actions/workflows/update-index.yml/runs?per_page=5'
$r = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
$r.workflow_runs | Select-Object id, status, conclusion, created_at, html_url | Format-Table -AutoSize
