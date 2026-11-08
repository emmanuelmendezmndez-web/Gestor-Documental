"""Bloqueo cooperativo de procesos sobre el directorio de datos de SIGED."""
from __future__ import annotations

import os
from pathlib import Path

from app.configuracion import DATA_DIR
from app.registro_restauracion import comprobar_estado


class BloqueoNoDisponible(RuntimeError):
    """No fue posible garantizar acceso coordinado a los datos."""


class _BloqueoSistema:
    def __init__(self, exclusivo: bool):
        self.exclusivo = exclusivo
        self.handle = None
        self._adquirir()

    def _adquirir(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ruta = str(DATA_DIR / ".siged-coordinacion.lock")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Overlapped(ctypes.Structure):
                _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                            ("hEvent", wintypes.HANDLE)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.LockFileEx.restype = wintypes.BOOL
            kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                            wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.UnlockFileEx.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            # No compartir borrado: el archivo no puede ser sustituido mientras esté abierto.
            handle = kernel.CreateFileW(ruta, 0xC0000000, 0x3, None, 4, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise BloqueoNoDisponible(f"No se pudo abrir el bloqueo de SIGED (Windows {ctypes.get_last_error()}).")
            overlapped = Overlapped()
            if not kernel.LockFileEx(handle, 1 | (2 if self.exclusivo else 0), 0, 1, 0, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                kernel.CloseHandle(handle)
                raise BloqueoNoDisponible(f"No se pudo adquirir el bloqueo de SIGED: servicio o restauración activos, o acceso denegado (Windows {error}).")
            self.handle, self._kernel, self._overlapped = handle, kernel, overlapped
        elif os.name == "posix":
            import fcntl
            try:
                fd = os.open(ruta, os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(fd, (fcntl.LOCK_EX if self.exclusivo else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                except BaseException:
                    os.close(fd)
                    raise
                self.handle = fd
            except OSError as error:
                raise BloqueoNoDisponible(f"No se pudo adquirir el bloqueo de SIGED: {error}") from error
        else:
            raise BloqueoNoDisponible("Sistema operativo sin bloqueo de SIGED compatible.")

    def cerrar(self):
        if self.handle is None:
            return
        handle, self.handle = self.handle, None
        if os.name == "nt":
            import ctypes
            try:
                if not self._kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(self._overlapped)):
                    raise OSError(ctypes.get_last_error(), "No se pudo liberar el bloqueo de SIGED")
            finally:
                self._kernel.CloseHandle(handle)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                os.close(handle)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cerrar()


class BloqueoDatos(_BloqueoSistema):
    def __init__(self, exclusivo: bool):
        super().__init__(exclusivo)
        try:
            comprobar_estado()
        except BaseException:
            self.cerrar()
            raise


def diagnosticar_restauracion(modo="profundo"):
    """Única entrada sin comprobación previa: solo produce un informe de lectura."""
    from app.diagnostico_restauracion import _inspeccionar
    with _BloqueoSistema(exclusivo=True):
        return _inspeccionar() if modo == "profundo" else _inspeccionar(modo)


def seleccionar_originales():
    """Selecciona únicamente para diagnóstico, bajo bloqueo exclusivo."""
    from app.seleccion_originales import _seleccionar
    with _BloqueoSistema(exclusivo=True):
        return _seleccionar()
