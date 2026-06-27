Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Lenovo\WorkBuddy\Claw\cs2-dashboard"
WshShell.Run """C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\pythonw.exe"" C:\Users\Lenovo\WorkBuddy\Claw\cs2-dashboard\run_update.py", 0, False
