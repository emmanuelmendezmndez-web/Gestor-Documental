"""Operaciones NTFS para el espacio privado de adjuntos."""

import ctypes as c
import os
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from functools import cache

from app.mensajeria.configuracion import directorio_configurado

LECTURA = 0x80000000
ESCRITURA = 0x40000000
BORRADO = 0x10000
ATRIBUTOS = 0x80
ABRIR = 3
CREAR = 1
COMPARTIR_LECTURA = 1
COMPARTIR_LECTURA_ESCRITURA = 3
REANALISIS = 0x400
DIRECTORIO = 0x10


class _Info(c.Structure):
    _fields_ = [
        ("atributos", w.DWORD), ("creado", w.FILETIME), ("acceso", w.FILETIME),
        ("escrito", w.FILETIME), ("volumen", w.DWORD), ("tam_alto", w.DWORD),
        ("tam_bajo", w.DWORD), ("enlaces", w.DWORD), ("id_alto", w.DWORD), ("id_bajo", w.DWORD),
    ]


@cache
def _kernel():
    if os.name != "nt":
        raise OSError("Los adjuntos requieren NTFS")
    k = c.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.GetFileInformationByHandle.argtypes = [w.HANDLE, c.POINTER(_Info)]
    k.GetFileInformationByHandle.restype = w.BOOL
    k.GetFileType.argtypes = [w.HANDLE]
    k.GetFileType.restype = w.DWORD
    k.SetFileInformationByHandle.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD]
    k.SetFileInformationByHandle.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    k.CloseHandle.restype = w.BOOL
    return k


def _abrir(ruta, acceso, compartir, modo, *, directorio=False):
    k = _kernel()
    flags = 0x00200000  # FILE_FLAG_OPEN_REPARSE_POINT
    if directorio:
        flags |= 0x02000000  # FILE_FLAG_BACKUP_SEMANTICS
    handle = k.CreateFileW(str(ruta), acceso, compartir, None, modo, flags, None)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    return handle


def _info(handle, *, directorio=False):
    k = _kernel()
    info = _Info()
    if not k.GetFileInformationByHandle(handle, c.byref(info)):
        raise c.WinError(c.get_last_error())
    if (k.GetFileType(handle) != 1 or info.atributos & REANALISIS
            or bool(info.atributos & DIRECTORIO) != directorio
            or (not directorio and (info.enlaces != 1 or not (info.id_alto or info.id_bajo)))):
        raise OSError("Identidad NTFS no verificable")
    return info


def _identidad(info):
    return ":".join(str(x) for x in (
        info.volumen, info.id_alto, info.id_bajo, info.creado.dwHighDateTime, info.creado.dwLowDateTime,
    ))


@contextmanager
def zona():
    with directorio_fijado(directorio_configurado() / "temporales") as contenedor:
        yield contenedor


@contextmanager
def directorio_fijado(contenedor):
    """Conserva abiertos los directorios sin compartir su borrado o traslado."""
    k = _kernel()
    with ExitStack() as pila:
        for ruta in (*reversed(contenedor.parents), contenedor):
            handle = _abrir(ruta, ATRIBUTOS, COMPARTIR_LECTURA_ESCRITURA, ABRIR, directorio=True)
            pila.callback(k.CloseHandle, handle)
            _info(handle, directorio=True)
        yield contenedor


def abrir(ruta, *, crear=False, escribir=False, trabajador=False):
    """Transfiere la propiedad del HANDLE al descriptor binario de Python."""
    import msvcrt

    escritura = crear or escribir or trabajador
    compartir = COMPARTIR_LECTURA_ESCRITURA if trabajador else (0 if escritura else COMPARTIR_LECTURA)
    handle = _abrir(ruta, LECTURA | (ESCRITURA if escritura else 0), compartir,
                   4 if trabajador else (CREAR if crear else ABRIR))
    try:
        identidad = _identidad(_info(handle))
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDWR if escritura else os.O_RDONLY))
    except BaseException:
        _kernel().CloseHandle(handle)
        raise
    try:
        return os.fdopen(fd, "r+b" if escritura else "rb", buffering=0), identidad
    except BaseException:
        os.close(fd)
        raise


def borrar(ruta, identidad, *, intencion_vacia=False):
    """Solicita el borrado del mismo objeto que se identificó por HANDLE."""
    try:
        handle = _abrir(ruta, BORRADO | ATRIBUTOS, 0, ABRIR)
    except FileNotFoundError:
        return
    k = _kernel()
    try:
        info = _info(handle)
        coincide = identidad is not None and identidad == _identidad(info)
        if not coincide and not (intencion_vacia and not (info.tam_alto or info.tam_bajo)):
            raise OSError("Evidencia insuficiente para el borrado")
        eliminar = c.c_ubyte(1)  # FILE_DISPOSITION_INFO.DeleteFile (BOOLEAN)
        if not k.SetFileInformationByHandle(handle, 4, c.byref(eliminar), c.sizeof(eliminar)):
            raise c.WinError(c.get_last_error())
    finally:
        k.CloseHandle(handle)
