Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
Remove-Item _final_cleanup.ps1, _run_verify.ps1 -ErrorAction SilentlyContinue
git add -A 2>&1
git commit -m "chore: final cleanup" 2>&1
git push 2>&1
