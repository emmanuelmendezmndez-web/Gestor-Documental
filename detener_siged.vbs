Option Explicit

Dim shell, sistemaArchivos, carpetaProyecto, archivoPowerShell, ejecutablePowerShell, comando
Set shell = CreateObject("WScript.Shell")
Set sistemaArchivos = CreateObject("Scripting.FileSystemObject")

carpetaProyecto = sistemaArchivos.GetParentFolderName(WScript.ScriptFullName)
archivoPowerShell = sistemaArchivos.BuildPath(carpetaProyecto, "detener_siged.ps1")
ejecutablePowerShell = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
comando = """" & ejecutablePowerShell & """ -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & archivoPowerShell & """"

shell.Run comando, 0, False

Set sistemaArchivos = Nothing
Set shell = Nothing
