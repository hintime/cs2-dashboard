Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
Remove-Item _cleanup.ps1, _verify.py, _verify.ps1, _verify_result.txt -ErrorAction SilentlyContinue
git add -A 2>&1
git commit -m "chore: remove remaining debug files" 2>&1
git push 2>&1
