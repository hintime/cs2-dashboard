Set-Location 'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 删除所有调试文件
Remove-Item _api_result.json, _body.json, _check_*.ps1, _debug_*.py, _gbk_result.json, _cp936_result.json, _git_*.ps1, _push_*.ps1, _raw_bytes.json, _run_*.ps1, _skill_result.json, _test_*.py, _test_*.ps1, _test_log.txt -ErrorAction SilentlyContinue

# 提交删除
git add -A 2>&1
git commit -m "chore: clean up debug files" 2>&1
git push 2>&1
