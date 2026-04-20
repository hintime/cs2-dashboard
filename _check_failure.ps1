[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$runId = '24653953667'
$url = "https://api.github.com/repos/hintime/cs2-dashboard/actions/runs/$runId/logs"
Write-Host "Fetching logs for run $runId..."
try {
    $headers = @{
        'Accept' = 'application/vnd.github.v3+json'
    }
    $r = Invoke-WebRequest -Uri $url -Headers $headers -Method Get
    Write-Host $r.Content.Substring(0, [Math]::Min(3000, $r.Content.Length))
} catch {
    Write-Host "Error: $_"
    Write-Host "Trying job logs..."
    $jobsUrl = "https://api.github.com/repos/hintime/cs2-dashboard/actions/runs/$runId/jobs"
    $jobs = Invoke-RestMethod -Uri $jobsUrl -Headers $headers
    $jobs.jobs | ForEach-Object {
        Write-Host "`n=== Job: $($_.name) ==="
        Write-Host "Status: $($_.status) Conclusion: $($_.conclusion)"
        $_.steps | ForEach-Object {
            Write-Host "  Step: $($_.name) - $($_.conclusion)"
        }
    }
}
