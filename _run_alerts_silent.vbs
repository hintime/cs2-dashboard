' 静默运行 Python 脚本，无窗口
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\update.py alerts", 0, False
