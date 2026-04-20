Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
git add index_collector.py
git commit -m "fix: undefined variable 'hour' → 'now_hour' in print statement"
git pull origin main --rebase
git push origin main
Write-Host "推送完成！"
