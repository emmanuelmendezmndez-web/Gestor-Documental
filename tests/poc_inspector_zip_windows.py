"""Integración experimental, sin extracción ni autorización de recuperación.

El protocolo del hijo es un código de salida fijo: no transmite rutas,
excepciones ni contenido. El padre lo convierte en un resultado estructurado.
El lector verifica los conteos de cierre ZIP/ZIP64 antes de aceptar la estructura.
"""
import ctypes as c
import io
import os
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from poc_job_windows import ejecutar
from poc_handle_windows import abrir


def inspeccionar(handle, plazo=5, limite_lectura=8 * 1024**2):
    # Rutas de código de confianza, nunca la ruta del archivo que se inspecciona.
    raiz = str(Path(__file__).resolve().parents[1])
    paquetes = str(Path(sys.prefix) / 'Lib' / 'site-packages')
    codigo = f'''
import sys, os, msvcrt
sys.path[:0] = [{raiz!r}, {paquetes!r}]
# No heredar configuración de SIGED para esta prueba aislada.
for nombre in list(os.environ):
    if nombre.startswith('GESTOR_'):
        del os.environ[nombre]
os.environ['GESTOR_ZIP_MAX_LECTURA_BYTES'] = {str(limite_lectura)!r}
try:
    from app.apertura_zip_acotada import abrir_zip_acotado, LimiteZip
    import zipfile
    # open_osfhandle entrega la propiedad al descriptor; fdopen la entrega al archivo.
    fd = msvcrt.open_osfhandle({handle}, os.O_RDONLY | os.O_BINARY)
    try:
        entrada = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    with entrada:
        with abrir_zip_acotado(entrada):
            pass
except LimiteZip:
    raise SystemExit(41)
except (zipfile.BadZipFile, ValueError, NotImplementedError):
    raise SystemExit(42)
except OSError:
    raise SystemExit(43)
except BaseException:
    raise SystemExit(44)
raise SystemExit(40)
'''
    try:
        eventos = ejecutar(codigo, plazo=plazo, heredados=(handle,))
    except (OSError, RuntimeError):
        return {'estado': 'inconcluso', 'aceptacion_estructural': False, 'listo_recuperacion': False}
    estados = {40: 'estructura_aceptable', 41: 'limite_lector', 42: 'zip_invalido',
               43: 'error_identificador_o_lectura', 44: 'inconcluso'}
    salidas = [e for e in eventos if e.startswith('salida_')]
    estado = 'inconcluso'
    if 'plazo_terminado' in eventos:
        estado = 'plazo_vencido'
    elif (len(salidas) == 1 and eventos[-1] == 'identificadores_cerrados'
          and 'asignacion_verificada' in eventos):
        estado = estados.get(int(salidas[0].split('_')[1]), 'inconcluso')
    return {'estado': estado, 'aceptacion_estructural': estado == 'estructura_aceptable',
            'listo_recuperacion': False}


@unittest.skipUnless(os.name == 'nt', 'Requiere Windows')
class InspectorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='siged-poc-inspector-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'ficticio.zip'
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, 'w') as z:
            z.writestr('storage/ficticio.txt', b'datos ficticios')
        self.path.write_bytes(salida.getvalue())

    def comprobar(self, esperado, **opciones):
        antes = self.path.read_bytes()
        with abrir(self.path) as handle:
            resultado = inspeccionar(handle, **opciones)
        self.assertEqual(resultado['estado'], esperado, resultado)
        self.assertFalse(resultado['listo_recuperacion'])
        self.assertEqual(resultado['aceptacion_estructural'], esperado == 'estructura_aceptable')
        self.assertEqual(self.path.read_bytes(), antes)
        self.assertEqual(list(self.root.iterdir()), [self.path])
        self.path.unlink()  # Comprueba cierre sin permisos de borrado compartidos.
        print(resultado)

    def test_valido(self):
        self.comprobar('estructura_aceptable')

    def test_corrupto(self):
        self.path.write_bytes(b'no es un ZIP')
        self.comprobar('zip_invalido')

    def test_conteo_contradictorio(self):
        data = bytearray(self.path.read_bytes())
        pos = data.rfind(b'PK\x05\x06')
        struct.pack_into('<HH', data, pos + 8, 2, 2)
        self.path.write_bytes(data)
        self.comprobar('zip_invalido')

    def test_limite(self):
        self.comprobar('limite_lector', limite_lectura=1)

    def test_plazo(self):
        self.comprobar('plazo_vencido', plazo=0)

    def test_identificador_invalido(self):
        resultado = inspeccionar(c.c_void_p(-1).value)
        self.assertEqual(resultado['estado'], 'inconcluso')
        self.assertFalse(resultado['aceptacion_estructural'])

    def test_resultado_incompleto(self):
        with patch(__name__ + '.ejecutar', return_value=['salida_40']):
            resultado = inspeccionar(1)
        self.assertEqual(resultado['estado'], 'inconcluso')
        self.assertFalse(resultado['aceptacion_estructural'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
