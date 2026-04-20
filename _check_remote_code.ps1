[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$url = 'https://raw.githubusercontent.com/hintime/cs2-dashboard/main/index_collector.py'
$r = Invoke-WebRequest -Uri $url -UseBasicParsing
$content = $r.Content
# 检查是否包含修复
if ($content -match "now_hour") {
    Write-Host "✅ 代码已更新：包含 now_hour 修复"
} else {
    Write-Host "❌ 代码未更新：仍是旧版本"
}
# 检查是否还包含 hour 变量错误
if ($content -match "f'=== {date_str} {hour}:00 ==='") {
    Write-Host "❌ 仍包含旧 bug：{hour}"
}
