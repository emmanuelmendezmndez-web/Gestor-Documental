Option Explicit

Dim shell, sistemaArchivos, carpetaProyecto, archivoBat
Set shell = CreateObject("WScript.Shell")
Set sistemaArchivos = CreateObject("Scripting.FileSystemObject")

carpetaProyecto = sistemaArchivos.GetParentFolderName(WScript.ScriptFullName)
archivoBat = sistemaArchivos.BuildPath(carpetaProyecto, "Iniciar SIGED.bat")

' Muestra el estado de arranque y conserva Ctrl+C como opción de cierre.
shell.Run """" & archivoBat & """", 1, False

Set sistemaArchivos = Nothing
Set shell = Nothing
