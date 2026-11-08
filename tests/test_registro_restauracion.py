"""Interrupciones de restauración sobre datos ficticios y procesos aislados."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RegistroRestauracionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="siged-registro-prueba-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        self.env.update(GESTOR_DATA_DIR=str(self.root), GESTOR_SECRET_KEY="clave-ficticia-para-pruebas-1234567890",
                        PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        self.run_code('''
from app.database import inicializar_db
from app.configuracion import DATA_DIR, STORAGE_DIR
from app.respaldo import crear_respaldo
inicializar_db(); STORAGE_DIR.mkdir(exist_ok=True)
(STORAGE_DIR / 'ficticio.txt').write_bytes(b'nuevo')
crear_respaldo(DATA_DIR / 'entrada.zip')
(STORAGE_DIR / 'ficticio.txt').write_bytes(b'anterior')
''')

    def run_code(self, code, expected=0):
        p = subprocess.run([sys.executable, "-c", code], env=self.env, text=True, capture_output=True, timeout=90,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(p.returncode, expected, p.stderr)
        return p

    def test_normal(self):
        self.run_code("from app.respaldo import restaurar_respaldo; from app.configuracion import DATA_DIR; restaurar_respaldo(DATA_DIR/'entrada.zip')")
        reg = json.loads((self.root / '.siged-restauracion.json').read_text(encoding='utf-8'))
        self.assertEqual(reg['estado'], 'finalizada')
        self.assertEqual((self.root / 'storage' / 'ficticio.txt').read_bytes(), b'nuevo')
        self.assertEqual((Path(reg['directorio']) / 'anterior-storage' / 'ficticio.txt').read_bytes(), b'anterior')
        self.assertTrue(Path(reg['respaldo_previo']).exists())
        self.run_code('import app.main')

    def test_cortes_y_arranque(self):
        for estado, paso in [('iniciada', 'preparada'), ('confirmada', 'base-instalar'), ('pendiente', 'storage-instalar')]:
            with self.subTest(paso=paso):
                # Cada subcaso usa un proceso de restauración sobre un conjunto propio.
                if paso != 'preparada':
                    self.tmp.cleanup()
                    self.setUp()
                code = f'''
import os
from app import respaldo
from app.configuracion import DATA_DIR
escribir = respaldo.escribir_registro
def cortar(registro):
    escribir(registro)
    if registro['estado'] == {estado!r} and registro['paso'] == {paso!r}:
        os._exit(53)
respaldo.escribir_registro = cortar
respaldo.restaurar_respaldo(DATA_DIR/'entrada.zip')
'''
                self.run_code(code, 53)
                reg = json.loads((self.root / '.siged-restauracion.json').read_text(encoding='utf-8'))
                self.assertEqual(reg['paso'], paso)
                self.assertTrue(Path(reg['respaldo_previo']).exists())
                if paso in ('base-instalar', 'storage-instalar'):
                    self.assertTrue((Path(reg['directorio']) / 'anterior-base').exists())
                activo = self.root / 'storage' / 'ficticio.txt'
                if paso == 'storage-instalar':
                    activo = Path(reg['directorio']) / 'anterior-storage' / 'ficticio.txt'
                antes = activo.read_bytes()
                r = self.run_code('import app.main', 1)
                self.assertIn('recuperación manual', r.stderr)
                self.assertEqual(activo.read_bytes(), antes)
                self.run_code('from app.coordinacion import BloqueoDatos; BloqueoDatos(False)', 1)

    def test_corrupto_y_auxiliares(self):
        (self.root / '.siged-restauracion.json').write_text('{', encoding='utf-8')
        self.assertIn('recuperación manual', self.run_code('import app.main', 1).stderr)
        (self.root / '.siged-restauracion.json').unlink()
        wal = self.root / 'gestor.db-wal'
        wal.write_bytes(b'ficticio')
        self.run_code("from app.respaldo import restaurar_respaldo; from app.configuracion import DATA_DIR; restaurar_respaldo(DATA_DIR/'entrada.zip')", 1)
        self.assertEqual(wal.read_bytes(), b'ficticio')
        self.assertEqual((self.root / 'storage' / 'ficticio.txt').read_bytes(), b'anterior')

    def test_sin_espacio_y_error_durante_cambio(self):
        self.run_code('''
from unittest.mock import patch
from collections import namedtuple
from app import respaldo
from app.configuracion import DATA_DIR
D = namedtuple('D', 'total used free')
with patch.object(respaldo.shutil, 'disk_usage', return_value=D(1, 1, 0)):
    try: respaldo.restaurar_respaldo(DATA_DIR/'entrada.zip')
    except RuntimeError as error: assert 'Espacio insuficiente' in str(error)
    else: raise AssertionError('Aceptó espacio insuficiente')
''')
        self.assertFalse((self.root / '.siged-restauracion.json').exists())
        self.run_code('''
from app import respaldo
from app.configuracion import DATA_DIR
original = respaldo.os.replace
def fallo(origen, destino):
    if str(destino).endswith('gestor.db'):
        raise OSError('espacio ficticio agotado')
    return original(origen, destino)
respaldo.os.replace = fallo
try: respaldo.restaurar_respaldo(DATA_DIR/'entrada.zip')
except OSError: pass
else: raise AssertionError('No falló el cambio')
''')
        reg = json.loads((self.root / '.siged-restauracion.json').read_text(encoding='utf-8'))
        self.assertEqual((reg['estado'], reg['paso']), ('pendiente', 'base-instalar'))
        self.assertTrue((Path(reg['directorio']) / 'anterior-base').exists())
        self.run_code('import app.main', 1)


if __name__ == '__main__':
    unittest.main()
