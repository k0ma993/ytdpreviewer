Set args = WScript.Arguments
If args.Count = 0 Then WScript.Quit 1
path = args(0)
Set sh = CreateObject("Wscript.Shell")
cmd = """C:\Users\yqeyw\AppData\Local\Programs\Python\Python312\pythonw.exe"" ""C:\Users\yqeyw\AppData\Local\YTDPreviewer\open.pyw"" "" & Chr(34) & path & Chr(34)
sh.Run cmd, 1, False
