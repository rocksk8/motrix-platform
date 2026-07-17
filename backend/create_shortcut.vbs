Dim WshShell, oShortcut
Set WshShell = CreateObject("WScript.Shell")

Dim batPath
batPath = WScript.ScriptFullName
batPath = Left(batPath, InStrRev(batPath, "\")) & "restart.bat"

Dim desktopPath
desktopPath = WshShell.SpecialFolders("Desktop")

Set oShortcut = WshShell.CreateShortcut(desktopPath & "\MOTRIX ERP - Restart.lnk")
oShortcut.TargetPath = batPath
oShortcut.WorkingDirectory = Left(batPath, InStrRev(batPath, "\") - 1)
oShortcut.Description = "MOTRIX ERP - Restart Server"
oShortcut.IconLocation = "C:\Windows\System32\cmd.exe,0"
oShortcut.Save

MsgBox "Desktop shortcut created!" & vbCrLf & desktopPath & "\MOTRIX ERP - Restart.lnk", vbInformation, "Done"
