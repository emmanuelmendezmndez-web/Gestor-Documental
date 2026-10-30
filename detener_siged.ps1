$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

function Mostrar-Mensaje([string]$texto, [System.Windows.Forms.MessageBoxIcon]$icono) {
    [void][System.Windows.Forms.MessageBox]::Show(
        $texto,
        "SIGED",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        $icono
    )
}

try {
    $conexion = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if (-not $conexion) {
        Mostrar-Mensaje "SIGED ya está apagado." ([System.Windows.Forms.MessageBoxIcon]::Information)
        exit 0
    }

    $proceso = Get-CimInstance Win32_Process -Filter "ProcessId = $($conexion.OwningProcess)"
    $esSiged = $proceso -and
        $proceso.Name -in @("python.exe", "pythonw.exe") -and
        $proceso.CommandLine -match '(?i)(?:-m\s+)?uvicorn\s+app\.main:app(?:\s|$)' -and
        $proceso.CommandLine -match '(?i)--port\s+8000(?:\s|$)'

    if (-not $esSiged) {
        Mostrar-Mensaje "El puerto 8000 lo está usando otro programa. No lo detuve." ([System.Windows.Forms.MessageBoxIcon]::Warning)
        exit 1
    }

    Stop-Process -Id $proceso.ProcessId -ErrorAction Stop
    Mostrar-Mensaje "SIGED se apagó correctamente." ([System.Windows.Forms.MessageBoxIcon]::Information)
} catch {
    Mostrar-Mensaje "No pude apagar SIGED. Cierra el servidor desde el Administrador de tareas o revisa la configuración de Windows." ([System.Windows.Forms.MessageBoxIcon]::Error)
    exit 1
}
