Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
git stash 2>&1
git pull --rebase 2>&1
git stash pop 2>&1
git add -A 2>&1
git commit -m "fix: update alerts with correct encoding" 2>&1
git push 2>&1
