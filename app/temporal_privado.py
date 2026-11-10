"""Directorios privados NTFS; no modifica ACL de rutas preexistentes."""
import ctypes
import os
import re
import shutil
import stat
import subprocess
import uuid
from contextlib import contextmanager
from ctypes import wintypes as w
from functools import lru_cache
from pathlib import Path

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
def directorio_privado(parent, *, nombre=None, conservar=False):
    parent = Path(parent).resolve(strict=True)
    _volumen_acl(parent)
    if nombre is not None and not re.fullmatch(
        r'(?:\.siged-(?:preparacion|conservacion)-operacion-[a-z0-9_]{8}|\.siged-mensajeria)',
        nombre,
    ):
        raise ValueError('Nombre de preparación inválido')
    path = parent / (nombre or ('.siged-verificacion-' + uuid.uuid4().hex))
    if os.path.lexists(path):
        raise FileExistsError('La preparación ya existe')
    env = os.environ.copy()
    env['SIGED_TEMP_PRIVADO'] = str(path)
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', _SCRIPT], env=env, capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise OSError('No se pudo establecer o verificar la ACL privada')
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise OSError('Directorio privado no verificable')
        yield path
    finally:
        if not conservar and path.exists():
            shutil.rmtree(path)


# La verificación de una preparación existente no modifica su contenido.
_SCRIPT_VERIFICAR = r'''
$ErrorActionPreference = 'Stop'
$p = $env:SIGED_TEMP_PRIVADO
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed = @($sid.Value, 'S-1-5-18', 'S-1-5-32-544') | Select-Object -Unique
$maximo = [int]$env:SIGED_MAX_ENTRADAS_ACL
$vistos = 1
$stack = New-Object 'System.Collections.Generic.Stack[string]'
if ($env:SIGED_ACL_ARCHIVO_VERIFICADO) {
  $stack.Push([System.IO.Path]::Combine($p, $env:SIGED_ACL_ARCHIVO_VERIFICADO))
}
$stack.Push($p)
while ($stack.Count -gt 0) {
  $item = $stack.Pop()
  $atributos = [System.IO.File]::GetAttributes($item)
  if (($atributos -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reanalisis no permitido' }
  $a = [System.IO.File]::GetAccessControl($item)
  if ($item -eq $p -and !$a.AreAccessRulesProtected) { throw 'ACL raiz no protegida' }
  $rules = $a.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])
  if ($rules.Count -ne $allowed.Count) { throw 'ACL inesperada' }
  foreach ($s in $allowed) {
    $r = @($rules | Where-Object { $_.IdentityReference.Value -eq $s })
    if ($r.Count -ne 1 -or $r[0].AccessControlType -ne 'Allow' -or $r[0].FileSystemRights -ne 'FullControl') { throw 'Acceso inesperado' }
  }
  if (($atributos -band [System.IO.FileAttributes]::Directory) -ne 0 -and $env:SIGED_ACL_SOLO_RAIZ -ne '1') {
    foreach ($child in [System.IO.Directory]::EnumerateFileSystemEntries($item)) {
      $vistos++
      if ($vistos -gt $maximo) { throw 'Limite de entradas excedido' }
      $stack.Push($child)
    }
  }
}
'''


def _verificar_acl(path, segundos, max_entradas, solo_raiz, archivo=""):
    path = Path(path)
    _volumen_acl(path.parent)
    env = os.environ.copy()
    env['SIGED_TEMP_PRIVADO'] = str(path)
    env['SIGED_MAX_ENTRADAS_ACL'] = str(max_entradas)
    env['SIGED_ACL_SOLO_RAIZ'] = '1' if solo_raiz else '0'
    env['SIGED_ACL_ARCHIVO_VERIFICADO'] = archivo
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        resultado = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', _SCRIPT_VERIFICAR], env=env, capture_output=True, timeout=segundos, check=False)
    except subprocess.TimeoutExpired as exc:
        raise OSError('Comprobación ACL incompleta') from exc
    if resultado.returncode:
        raise OSError('ACL privada no verificable')


def verificar_acl_privada(path, segundos, max_entradas=300000):
    """Comprueba ACL del árbol existente sin seguir puntos de reanálisis."""
    _verificar_acl(path, segundos, max_entradas, False)


def verificar_acl_base_privada(path, nombre, segundos):
    """Verifica raíz y archivo SQLite sin recorrer objetos ajenos a la lectura."""
    if not re.fullmatch(r"[a-z0-9_]+\.sqlite3", nombre):
        raise ValueError("Nombre de base privada inválido")
    path = Path(path)
    huellas = _huella_acl(path), _huella_acl(path / nombre)
    _confirmar_acl_base(path, nombre, segundos, huellas)


@lru_cache(maxsize=1)
def _api_descriptor_acl():
    api = ctypes.WinDLL("advapi32", use_last_error=True).GetFileSecurityW
    api.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    api.restype = w.BOOL
    return api


def _huella_acl(path):
    info = path.lstat()
    if not info.st_ino or getattr(info, "st_file_attributes", 0) & 0x400:
        raise OSError("Identidad del objeto protegido no verificable")
    api = _api_descriptor_acl()
    # OWNER | GROUP | DACL. NTFS acota el descriptor a 64 KiB.
    descriptor = ctypes.create_string_buffer(65536)
    usados = w.DWORD()
    if not api(str(path), 7, descriptor, len(descriptor), ctypes.byref(usados)) or not 0 < usados.value <= len(descriptor):
        raise OSError("Descriptor ACL no verificable")
    return info.st_dev, info.st_ino, descriptor.raw[:usados.value]


@lru_cache(maxsize=4)
def _confirmar_acl_base(path, nombre, segundos, huellas):
    # Solo se reutiliza el resultado con identidad y descriptor idénticos
    # dentro del mismo proceso SIGED, que opera con una sola cuenta.
    _verificar_acl(path, segundos, 2, True, nombre)
    if huellas != (_huella_acl(path), _huella_acl(path / nombre)):
        raise OSError("ACL cambió durante la comprobación")


def verificar_acl_raiz_conservacion(path, segundos, max_entradas=300000):
    """Verifica solo el contenedor: los originales conservan sus ACL previas."""
    if not re.fullmatch(r'\.siged-conservacion-operacion-[a-z0-9_]{8}', Path(path).name):
        raise ValueError('No es un contenedor de conservación')
    _verificar_acl(path, segundos, max_entradas, True)
