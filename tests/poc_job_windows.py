"""POC independiente: python tests/poc_job_windows.py (solo Windows)."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest


class STARTUPINFO(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR),
                ('title', w.LPWSTR)] + [(n, w.DWORD) for n in
                ('x', 'y', 'xs', 'ys', 'xc', 'yc', 'fill', 'flags')] + [
                ('show', w.WORD), ('reserved2size', w.WORD), ('reserved2', c.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class PROCESSINFO(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class STARTUPINFOEX(c.Structure):
    _fields_ = [('startup', STARTUPINFO), ('attributes', c.c_void_p)]


class BASIC(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                ('min_ws', c.c_size_t), ('max_ws', c.c_size_t), ('active', w.DWORD),
                ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IO(c.Structure):
    _fields_ = [(n, c.c_uint64) for n in ('ro', 'wo', 'oo', 'rb', 'wb', 'ob')]


class EXTENDED(c.Structure):
    _fields_ = [('basic', BASIC), ('io', IO), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


class COMPLETION(c.Structure):
    _fields_ = [('key', c.c_void_p), ('port', w.HANDLE)]


def api():
    k = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD,
                            c.c_void_p, w.LPCWSTR, c.POINTER(STARTUPINFO), c.POINTER(PROCESSINFO)], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'IsProcessInJob': ([w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)], w.BOOL),
        'ResumeThread': ([w.HANDLE], w.DWORD),
        'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'GetExitCodeProcess': ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
        'InitializeProcThreadAttributeList': ([c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
        'UpdateProcThreadAttribute': ([c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p], w.BOOL),
        'DeleteProcThreadAttributeList': ([c.c_void_p], None),
        'CreateIoCompletionPort': ([w.HANDLE, w.HANDLE, c.c_size_t, w.DWORD], w.HANDLE),
        'GetQueuedCompletionStatus': ([w.HANDLE, c.POINTER(w.DWORD), c.POINTER(c.c_size_t),
                                       c.POINTER(c.c_void_p), w.DWORD], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(k, name); fn.argtypes = args; fn.restype = result
    return k


def check(value):
    if not value:
        raise c.WinError(c.get_last_error())
    return value


def ejecutar(codigo, plazo=5, fallo_asignacion=False, observar_memoria=False, heredados=()):
    k = api()
    executable = Path(sys.base_prefix) / 'python.exe'
    if not executable.is_file():
        raise RuntimeError('No se encontró el intérprete base real')
    job = check(k.CreateJobObjectW(None, None))
    pi = PROCESSINFO()
    port = None
    atributos = None
    eventos = []
    try:
        if observar_memoria:
            port = check(k.CreateIoCompletionPort(w.HANDLE(-1), None, 0, 1))
            asociacion = COMPLETION(1, port)
            check(k.SetInformationJobObject(job, 7, c.byref(asociacion), c.sizeof(asociacion)))
        limites = EXTENDED()
        limites.basic.flags = 0x2000 | 0x100 | 0x200 | 0x8
        limites.basic.active = 1
        limites.process_memory = limites.job_memory = 128 * 1024**2
        check(k.SetInformationJobObject(job, 9, c.byref(limites), c.sizeof(limites)))
        verificado = EXTENDED()
        check(k.QueryInformationJobObject(job, 9, c.byref(verificado), c.sizeof(verificado), None))
        if (verificado.basic.flags != limites.basic.flags or verificado.basic.active != 1
                or verificado.process_memory != limites.process_memory
                or verificado.job_memory != limites.job_memory):
            raise RuntimeError('Los límites consultados no coinciden')
        eventos.append('limites_verificados')
        si = STARTUPINFOEX(); si.startup.cb = c.sizeof(STARTUPINFO)
        flags = 0x4 | 0x08000000
        if heredados:
            longitud = c.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, c.byref(longitud))
            if c.get_last_error() != 122 or not longitud.value:
                raise RuntimeError('No se pudo dimensionar la lista de atributos')
            buffer = c.create_string_buffer(longitud.value)
            check(k.InitializeProcThreadAttributeList(buffer, 1, 0, c.byref(longitud)))
            atributos = buffer
            lista = (w.HANDLE * len(heredados))(*heredados)
            check(k.UpdateProcThreadAttribute(buffer, 0, 0x20002, lista, c.sizeof(lista), None, None))
            si.attributes = c.cast(buffer, c.c_void_p)
            si.startup.cb = c.sizeof(si)
            flags |= 0x00080000
        cmd = c.create_unicode_buffer(subprocess.list2cmdline([str(executable), '-I', '-S', '-c', codigo]))
        check(k.CreateProcessW(str(executable), cmd, None, None, bool(heredados), flags,
                               None, None, c.byref(si.startup), c.byref(pi)))
        eventos.append('creado_suspendido')
        if k.WaitForSingleObject(pi.process, 50) != 258:
            raise RuntimeError('El proceso suspendido no sigue activo')
        if fallo_asignacion:
            eventos.append('fallo_asignacion_simulado')
            return eventos
        check(k.AssignProcessToJobObject(job, pi.process))
        pertenece = w.BOOL()
        check(k.IsProcessInJob(pi.process, job, c.byref(pertenece)))
        if not pertenece.value:
            raise RuntimeError('No se confirmó pertenencia al Job')
        eventos.append('asignacion_verificada')
        if k.ResumeThread(pi.thread) != 1:
            raise RuntimeError('Estado de suspensión inesperado')
        eventos.append('reanudado')
        resultado = k.WaitForSingleObject(pi.process, int(plazo * 1000))
        if resultado == 258:
            check(k.TerminateJobObject(job, 124))
            if k.WaitForSingleObject(pi.process, 5000) != 0:
                raise RuntimeError('No se confirmó terminación tras el plazo')
            eventos.append('plazo_terminado')
        elif resultado != 0:
            raise RuntimeError('Falló la espera del proceso')
        else:
            code = w.DWORD(); check(k.GetExitCodeProcess(pi.process, c.byref(code)))
            eventos.append('salida_' + str(code.value))
        if observar_memoria:
            # Notificaciones no garantizadas: su ausencia nunca demuestra éxito.
            for _ in range(32):
                mensaje, clave, pid = w.DWORD(), c.c_size_t(), c.c_void_p()
                if not k.GetQueuedCompletionStatus(port, c.byref(mensaje), c.byref(clave), c.byref(pid), 100):
                    if c.get_last_error() == 258:
                        break
                    raise c.WinError(c.get_last_error())
                if clave.value == 1 and pid.value == pi.pid and mensaje.value in (9, 10):
                    eventos.append('limite_memoria_job_' + str(mensaje.value))
        return eventos
    finally:
        try:
            if pi.process and k.WaitForSingleObject(pi.process, 0) != 0:
                check(k.TerminateProcess(pi.process, 125))
                if k.WaitForSingleObject(pi.process, 5000) != 0:
                    raise RuntimeError('No se confirmó limpieza del proceso')
                eventos.append('proceso_terminado_en_limpieza')
        finally:
            if atributos is not None:
                k.DeleteProcThreadAttributeList(atributos)
            errores = []
            for handle in (pi.thread, pi.process, job, port):
                if handle and not k.CloseHandle(handle):
                    errores.append(c.get_last_error())
            if errores:
                raise RuntimeError('Falló CloseHandle: ' + str(errores))
            eventos.append('identificadores_cerrados')


@unittest.skipUnless(os.name == 'nt', 'Requiere Windows')
class JobPOCTest(unittest.TestCase):
    def test_memoria(self):
        codigo = '''
import ctypes as c
from ctypes import wintypes as w
k = c.WinDLL('kernel32', use_last_error=True)
k.VirtualAlloc.argtypes = [c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
k.VirtualAlloc.restype = c.c_void_p
k.VirtualFree.argtypes = [c.c_void_p, c.c_size_t, w.DWORD]
k.VirtualFree.restype = w.BOOL
# Primero comprobar una asignación mínima, sin tocar las páginas.
pequeno = k.VirtualAlloc(None, 4096, 0x3000, 4)
if not pequeno:
    raise SystemExit(60000)
if not k.VirtualFree(pequeno, 0, 0x8000):
    raise SystemExit(60002)
c.set_last_error(0)
grande = k.VirtualAlloc(None, 129 * 1024**2, 0x3000, 4)
error = c.get_last_error()
if grande:
    k.VirtualFree(grande, 0, 0x8000)
    raise SystemExit(60001)
raise SystemExit(error or 60003)
'''
        inicio = time.monotonic()
        eventos = ejecutar(codigo, observar_memoria=True)
        print({'solicitud_MiB': 129, 'limite_MiB': 128,
               'duracion_s': round(time.monotonic() - inicio, 3), 'eventos': eventos})
        self.assertEqual(eventos[-1], 'identificadores_cerrados')
        self.assertNotIn('plazo_terminado', eventos)
        self.assertNotIn('proceso_terminado_en_limpieza', eventos)
        self.assertNotIn('salida_60001', eventos, 'Windows aceptó la solicitud excesiva')
        salidas = [e for e in eventos if e.startswith('salida_')]
        self.assertEqual(len(salidas), 1)
        error = int(salidas[0].split('_')[1])
        if error not in (8, 14, 1455, 1816):
            self.skipTest('Inconcluso: fallo inesperado o asignación mínima fallida: ' + str(error))
        if not any(e.startswith('limite_memoria_job_') for e in eventos):
            self.skipTest('Rechazo observado, pero sin notificación que permita atribuirlo al Job')

    def test_normal(self):
        eventos = ejecutar('raise SystemExit(37)')
        self.assertEqual(eventos, ['limites_verificados', 'creado_suspendido',
                         'asignacion_verificada', 'reanudado', 'salida_37', 'identificadores_cerrados'])
        print(eventos)

    def test_fallo_asignacion(self):
        eventos = ejecutar('raise SystemExit(37)', fallo_asignacion=True)
        self.assertNotIn('reanudado', eventos)
        self.assertIn('proceso_terminado_en_limpieza', eventos)
        self.assertEqual(eventos[-1], 'identificadores_cerrados')
        print(eventos)

    def test_plazo(self):
        inicio = time.monotonic()
        eventos = ejecutar('import time; time.sleep(30)', plazo=0.5)
        self.assertIn('plazo_terminado', eventos)
        self.assertEqual(eventos[-1], 'identificadores_cerrados')
        self.assertLess(time.monotonic() - inicio, 10)
        print(eventos)


if __name__ == '__main__':
    unittest.main(verbosity=2)
