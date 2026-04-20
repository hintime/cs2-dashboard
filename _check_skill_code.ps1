[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location 'C:\Users\Lenovo\.qclaw\workspace\skills\csqaq-market-lookup\scripts'
Select-String -Path 'csqaq_api.py' -Pattern 'decode' | Format-Table -AutoSize
