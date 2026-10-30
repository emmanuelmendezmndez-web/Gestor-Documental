Option Explicit

Dim shell, sistemaArchivos, carpetaProyecto, archivoBat
Set shell = CreateObject("WScript.Shell")
Set sistemaArchivos = CreateObject("Scripting.FileSystemObject")

carpetaProyecto = sistemaArchivos.GetParentFolderName(WScript.ScriptFullName)
archivoBat = sistemaArchivos.BuildPath(carpetaProyecto, "Iniciar SIGED.bat")

' Ejecuta el lanzador existente sin mostrar la ventana de comandos.
shell.Run """" & archivoBat & """", 0, False

Set sistemaArchivos = Nothing
Set shell = Nothing
