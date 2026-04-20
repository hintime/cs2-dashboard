[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$url = 'https://api.github.com/repos/hintime/cs2-dashboard/actions/workflows/update-index.yml/runs?per_page=5'
$r = Invoke-RestMethod -Uri $url -Method Get
$r.workflow_runs | Select-Object id, status, conclusion, created_at, updated_at | Format-Table -AutoSize
