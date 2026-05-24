cd 'C:\Users\Lenovo\cs2-dashboard'
$env:GIT_TERMINAL_PROMPT='0'
$env:GIT_ASKPASS='echo'
Write-Host 'Fetching...'
git -c http.sslBackend=openssl -c http.sslVerify=false fetch origin main
if ($?) {
    Write-Host 'Resetting...'
    git -c http.sslBackend=openssl -c http.sslVerify=false reset --hard origin/main
    Write-Host 'Done!'
} else {
    Write-Host 'Fetch failed'
}
