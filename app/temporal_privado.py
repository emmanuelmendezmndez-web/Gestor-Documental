"""Directorios privados NTFS; no modifica ACL de rutas preexistentes."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import shutil
import subprocess
import uuid

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$p = $env:SIGED_TEMP_PRIVADO
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed = @($sid.Value, 'S-1-5-18', 'S-1-5-32-544') | Select-Object -Unique
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
foreach ($s in $allowed) {
  $id = New-Object System.Security.Principal.SecurityIdentifier($s)
  $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($id, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
  $acl.AddAccessRule($rule)
}
$acl.SetOwner($sid)
# .NET Framework pasa el descriptor a CreateDirectory: no hay creación abierta previa.
if ([System.IO.Directory]::Exists($p)) { throw 'Ruta ya existente' }
$d = New-Object System.IO.DirectoryInfo($p)
$d.Create($acl)
function Check($item, $root) {
  $a = [System.IO.File]::GetAccessControl($item)
  if ($root -and !$a.AreAccessRulesProtected) { throw 'Herencia abierta' }
  $rules = $a.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])
  if ($rules.Count -ne $allowed.Count) { throw 'ACL inesperada' }
  foreach ($s in $allowed) {
    $r = @($rules | Where-Object { $_.IdentityReference.Value -eq $s })
    if ($r.Count -ne 1 -or $r[0].AccessControlType -ne 'Allow' -or $r[0].FileSystemRights -ne 'FullControl') { throw 'Acceso inesperado' }
  }
}
Check $p $true
$sub = [System.IO.Directory]::CreateDirectory([System.IO.Path]::Combine($p,'prueba-herencia'))
$f = [System.IO.Path]::Combine($sub.FullName,'prueba')
[System.IO.File]::WriteAllText($f,'ficticio')
Check $sub.FullName $false
Check $f $false
[System.IO.File]::Delete($f)
$sub.Delete()
'''


def _volumen_acl(parent):
    if os.name != 'nt':
        raise OSError('Esta operación requiere Windows con ACL persistentes')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetVolumePathNameW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    k.GetVolumeInformationW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD]
    volume = ctypes.create_unicode_buffer(32768)
    flags = w.DWORD()
    fs = ctypes.create_unicode_buffer(64)
    if not k.GetVolumePathNameW(str(parent), volume, len(volume)) or not k.GetVolumeInformationW(volume.value, None, 0, None, None, ctypes.byref(flags), fs, len(fs)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not flags.value & 8 or fs.value != 'NTFS':
        raise OSError('Se requiere NTFS con ACL persistentes')


@contextmanager
def directorio_privado(parent):
    parent = Path(parent).resolve(strict=True)
    _volumen_acl(parent)
    path = parent / ('.siged-verificacion-' + uuid.uuid4().hex)
    env = os.environ.copy()
    env['SIGED_TEMP_PRIVADO'] = str(path)
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', _SCRIPT], env=env, capture_output=True, timeout=30)
        if result.returncode:
            raise OSError('No se pudo establecer o verificar la ACL privada')
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)

