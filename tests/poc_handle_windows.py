"""ZIP ficticio leído por handle; ejecutar con Python en Windows. Sin extracción."""
import ctypes as c
from ctypes import wintypes as w
from contextlib import contextmanager
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from poc_job_windows import ejecutar, check, api


class SECURITY(c.Structure):
    _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]


@contextmanager
def abrir(path):
    k = api()
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(SECURITY), w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    sa = SECURITY(c.sizeof(SECURITY), None, True)
    h = k.CreateFileW(str(path), 0x80000000, 1, c.byref(sa), 3, 0x80, None)
    if h == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        yield h
    finally:
        check(k.CloseHandle(h))


def lector(handle, esperado):
    # No se incluye la ruta. open_osfhandle transfiere la propiedad al descriptor.
    return f'''
import os, msvcrt, hashlib
try:
    fd = msvcrt.open_osfhandle({handle}, os.O_RDONLY | os.O_BINARY)
    with os.fdopen(fd, 'rb') as entrada:
        digest = hashlib.sha256()
        for bloque in iter(lambda: entrada.read(4096), b''):
            digest.update(bloque)
    raise SystemExit(37 if digest.hexdigest() == {esperado!r} else 38)
except OSError:
    raise SystemExit(39)
'''


@unittest.skipUnless(os.name == 'nt', 'Requiere Windows')
class TransferenciaTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='siged-poc-handle-')
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'ficticio.zip'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('ficticio.txt', b'contenido completamente ficticio')
        self.datos = buffer.getvalue()
        self.path.write_bytes(self.datos)
        self.hash = hashlib.sha256(self.datos).hexdigest()

    def comprobar_cierre(self):
        self.assertEqual(self.path.read_bytes(), self.datos)
        self.path.unlink()  # Solo el ZIP ficticio: detecta handles residuales sin compartir borrado.

    def test_transferencia(self):
        with abrir(self.path) as h:
            codigo = lector(h, self.hash)
            self.assertNotIn(str(self.path), codigo)
            eventos = ejecutar(codigo, heredados=(h,))
            self.assertIn('salida_37', eventos)
            self.assertEqual(eventos[-1], 'identificadores_cerrados')
        self.comprobar_cierre()

    def test_identificador_ajeno_no_heredado(self):
        k = api()
        k.CreateEventW.argtypes = [c.POINTER(SECURITY), w.BOOL, w.BOOL, w.LPCWSTR]
        k.CreateEventW.restype = w.HANDLE
        sa = SECURITY(c.sizeof(SECURITY), None, True)
        ajeno = check(k.CreateEventW(c.byref(sa), True, False, None))
        try:
            with abrir(self.path) as h:
                prefijo = f'''
import ctypes as c
from ctypes import wintypes as w
k = c.WinDLL('kernel32', use_last_error=True)
k.SetEvent.argtypes = [w.HANDLE]
k.SetEvent.restype = w.BOOL
# Los números de handle pueden reutilizarse; comprobar el objeto en el padre.
k.SetEvent({ajeno})
'''
                eventos = ejecutar(prefijo + lector(h, self.hash), heredados=(h,))
                self.assertIn('salida_37', eventos)
                self.assertEqual(k.WaitForSingleObject(ajeno, 0), 258)
        finally:
            check(k.CloseHandle(ajeno))
        self.comprobar_cierre()

    def test_apertura_fallida(self):
        with self.assertRaises(OSError):
            with abrir(self.path.parent / 'inexistente.zip'):
                self.fail('No debe continuar después de fallar CreateFileW')
        self.comprobar_cierre()

    def test_escritura_borrado_rechazados(self):
        with abrir(self.path):
            with self.assertRaises(PermissionError):
                with self.path.open('r+b'): pass
            with self.assertRaises(PermissionError): self.path.unlink()
        self.comprobar_cierre()

    def test_hash_incorrecto(self):
        with abrir(self.path) as h:
            eventos = ejecutar(lector(h, '0' * 64), heredados=(h,))
            self.assertIn('salida_38', eventos)
            self.assertNotIn('salida_37', eventos)
        self.comprobar_cierre()

    def test_transferencia_invalida(self):
        with self.assertRaises(OSError):
            ejecutar('raise SystemExit(37)', heredados=(c.c_void_p(-1).value,))
        self.comprobar_cierre()

    def test_fallo_asignacion(self):
        with abrir(self.path) as h:
            eventos = ejecutar(lector(h, self.hash), heredados=(h,), fallo_asignacion=True)
            self.assertNotIn('reanudado', eventos)
            self.assertIn('proceso_terminado_en_limpieza', eventos)
        self.comprobar_cierre()

    def test_plazo(self):
        with abrir(self.path) as h:
            eventos = ejecutar('import time; time.sleep(30)', heredados=(h,), plazo=0.5)
            self.assertIn('plazo_terminado', eventos)
            self.assertNotIn('salida_37', eventos)
        self.comprobar_cierre()


if __name__ == '__main__':
    unittest.main(verbosity=2)
