"""Señal de cierre para el lanzador y el acceso directo de Windows."""

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from hashlib import sha256


def _api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    firmas = {
        "CreateEventW": ([wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenEventW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetEvent": ([wintypes.HANDLE], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for nombre, (argumentos, resultado) in firmas.items():
        funcion = getattr(api, nombre)
        funcion.argtypes, funcion.restype = argumentos, resultado
    return api


def _nombre(raiz):
    huella = sha256(str(raiz).casefold().encode()).hexdigest()[:32]
    return "Local\\SIGED-" + huella


@contextmanager
def escuchar(raiz):
    api = _api()
    ctypes.set_last_error(0)
    evento = api.CreateEventW(None, True, False, _nombre(raiz))
    if not evento:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            raise FileExistsError("El lanzador de este proyecto ya está en ejecución.")
        yield lambda: api.WaitForSingleObject(evento, 0) == 0
    finally:
        api.CloseHandle(evento)


class _Limites(ctypes.Structure):
    _fields_ = [
        ("tiempo_proceso", ctypes.c_longlong), ("tiempo_job", ctypes.c_longlong), ("banderas", wintypes.DWORD),
        ("min_memoria", ctypes.c_size_t), ("max_memoria", ctypes.c_size_t), ("procesos", wintypes.DWORD),
        ("afinidad", ctypes.c_size_t), ("prioridad", wintypes.DWORD), ("planificacion", wintypes.DWORD),
    ]


class _LimitesExtendidos(ctypes.Structure):
    _fields_ = [
        ("basicos", _Limites), ("contadores_io", ctypes.c_ulonglong * 6), ("memoria", ctypes.c_size_t * 4),
    ]


def custodiar_proceso(pid):
    """Windows elimina los hijos de este Job si el lanzador pierde su handle."""
    api = _api()
    api.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    job = api.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limites = _LimitesExtendidos()
        limites.basicos.banderas = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(job, 9, ctypes.byref(limites), ctypes.sizeof(limites)):
            raise ctypes.WinError(ctypes.get_last_error())
        proceso = api.OpenProcess(0x0101, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not proceso:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not api.AssignProcessToJobObject(job, proceso):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            api.CloseHandle(proceso)
    except BaseException:
        api.CloseHandle(job)
        raise
    return lambda: api.CloseHandle(job)


def solicitar(raiz):
    api = _api()
    evento = api.OpenEventW(0x0002, False, _nombre(raiz))  # EVENT_MODIFY_STATE
    if not evento:
        error = ctypes.get_last_error()
        if error == 2:
            return False
        raise ctypes.WinError(error)
    try:
        if not api.SetEvent(evento):
            raise ctypes.WinError(ctypes.get_last_error())
        return True
    finally:
        api.CloseHandle(evento)
