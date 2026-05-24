' CS2 Dashboard — 静默更新启动器
' 运行时不显示任何窗口

Dim shell
Set shell = CreateObject("WScript.Shell")

' 后台静默运行 run_update.cmd
shell.Run "cmd /c """ & Replace(WScript.ScriptFullName, ".vbs", ".cmd") & """", 0, False

Set shell = Nothing
