[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location 'C:\Users\Lenovo\.qclaw\workspace'

# 直接调用 skill CLI 测试
$env:CSQAQ_API_TOKEN = "csqaqapi_HXGPY1R7L5W7K7F3O4K1E2N8"
$output = python 'skills\csqaq-market-lookup\scripts\csqaq_api.py' call --path '/api/v1/info/get_rank_list' --method POST 2>&1
Write-Host "=== Raw output (first 500 chars) ==="
Write-Host $output.Substring(0, [Math]::Min(500, $output.Length))
