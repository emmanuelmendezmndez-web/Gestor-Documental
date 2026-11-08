"""Esquemas e inventarios con archivos ficticios; no restaura bases de datos."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aislamiento import exigir_directorio_temporal
PADRE = exigir_directorio_temporal("siged-prueba-registro-v2-")
from app import registro_restauracion as r
from app import inventario_restauracion as inv


class EsquemaTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=PADRE)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for modulo, valores in ((r, {"DATA_DIR": self.root, "REGISTRO": self.root / '.siged-restauracion.json',
                                    "RAIZ": self.root / '.siged-restauraciones', "BACKUP_DIR": self.root / 'respaldos'}),
                                (inv, {"DB_PATH": self.root / 'gestor.db', "STORAGE_DIR": self.root / 'storage',
                                       "SECRET_PATH": self.root / '.secret_key'})):
            parche = patch.multiple(modulo, **valores)
            parche.start()
            self.addCleanup(parche.stop)
        inv.DB_PATH.write_bytes(b'base anterior ficticia')
        inv.STORAGE_DIR.mkdir()
        (inv.STORAGE_DIR / 'documento.txt').write_bytes(b'anterior')
        r.BACKUP_DIR.mkdir()
        self.previo = r.BACKUP_DIR / 'previo-restauracion-20260101-010101.zip'
        self.previo.write_bytes(b'contenido ficticio para inventario, no ZIP restaurable')
        self.op = r.RAIZ / 'operacion-abcdefgh'
        (self.op / 'validado' / 'database').mkdir(parents=True)
        (self.op / 'validado' / 'database' / 'gestor.db').write_bytes(b'base preparada ficticia')
        (self.op / 'validado' / 'storage').mkdir()
        (self.op / 'validado' / 'storage' / 'documento.txt').write_bytes(b'preparado')
        (self.op / 'validado' / 'secrets').mkdir()
        (self.op / 'validado' / 'secrets' / 'session_key').write_bytes(b'clave-ficticia')
        self.datos = {"version": 2, "operacion": self.op.name, "directorio": str(self.op),
                      "respaldo_previo": str(self.previo), "estado": "iniciada", "paso": "preparada",
                      "inventario": inv.publicar(self.op, self.previo), "clave_origen": "entorno",
                      "pasos": r.CAMBIOS[:4], "secuencia": 0}

    def finalizar(self):
        r.escribir(self.datos)
        self.datos.update(estado='finalizada', paso='verificada')
        r.escribir(self.datos)

    def test_separacion_ausencias_y_huellas(self):
        inv.verificar(self.op, self.datos['inventario'])
        filas = [json.loads(l) for l in (self.op / 'inventario.jsonl').read_text().splitlines()]
        old = next(f for f in filas if f['conjunto'] == 'anterior' and f['ruta'] == 'base')
        nuevo = next(f for f in filas if f['conjunto'] == 'preparado' and f['ruta'] == 'base')
        self.assertNotEqual(old['sha256'], nuevo['sha256'])
        self.assertIn({'conjunto': 'anterior', 'ruta': 'clave', 'tipo': 'ausente'}, filas)
        self.assertEqual(old['sha256'], hashlib.sha256(inv.DB_PATH.read_bytes()).hexdigest())
        before = (self.op / 'inventario.jsonl').read_bytes()
        with self.assertRaises(FileExistsError): inv.publicar(self.op, self.previo)
        self.assertEqual(before, (self.op / 'inventario.jsonl').read_bytes())

    def test_truncados_duplicados_tipos_y_rutas(self):
        for texto in ('{', '{"version":1,"version":2}', '[]'):
            r.REGISTRO.write_text(texto)
            with self.assertRaises(RuntimeError): r.comprobar_estado()
        for campo, valor in [('version', True), ('estado', 'desconocido'), ('paso', 'clave-instalar'),
                             ('directorio', str(self.root)), ('respaldo_previo', str(self.root / 'externo.zip')),
                             ('secuencia', 999), ('inventario', {}), ('clave_origen', 'otro')]:
            datos = copy.deepcopy(self.datos); datos[campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ValueError): r.analizar(datos)
        datos = copy.deepcopy(self.datos); datos['estado'] = 'finalizada'
        with self.assertRaises(ValueError): r.analizar(datos)

    def test_ausente_pendiente_y_arranque_sin_escrituras(self):
        antes = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaises(RuntimeError): r.comprobar_estado()
        despues = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(antes, despues)
        env = os.environ.copy(); env['GESTOR_DATA_DIR'] = str(self.root)
        proceso = subprocess.run([sys.executable, '-c', 'import app.main'], env=env, capture_output=True, timeout=30)
        self.assertNotEqual(proceso.returncode, 0)
        self.assertEqual(inv.DB_PATH.read_bytes(), b'base anterior ficticia')
        self.assertFalse(inv.SECRET_PATH.exists())

    def test_finalizada_sin_principal_y_cambios_legitimos(self):
        self.finalizar()
        r.comprobar_estado()
        r.REGISTRO.unlink()
        inv.DB_PATH.write_bytes(b'cambio legitimo posterior')
        r.comprobar_estado()

    def test_inventario_modificado_y_faltante(self):
        self.finalizar()
        archivo = self.op / 'inventario.jsonl'
        original = archivo.read_bytes()
        archivo.write_bytes(original.replace(b'anterior', b'Anterior', 1))
        with self.assertRaises(RuntimeError): r.comprobar_estado()
        archivo.unlink()
        with self.assertRaises(RuntimeError): r.comprobar_estado()

    def test_contradiccion_constancias(self):
        self.finalizar()
        datos = json.loads((self.op / 'finalizada.json').read_text())
        datos['inventario']['sha256'] = '0' * 64
        (self.op / 'finalizada.json').write_text(json.dumps(datos))
        with self.assertRaises(RuntimeError): r.comprobar_estado()

    def test_finalizada_no_oculta_otra_operacion_incierta(self):
        self.finalizar()
        (r.RAIZ / 'operacion-12345678').mkdir()
        with self.assertRaises(RuntimeError): r.comprobar_estado()

    def test_v1_sin_inventar_evidencia(self):
        (self.op / 'inventario.jsonl').unlink()
        datos = {k: v for k, v in self.datos.items() if k in r.BASE}
        datos.update(version=1, estado='finalizada', paso='verificada')
        r.escribir(datos)
        r.comprobar_estado()
        r.conservar_legado()
        r.REGISTRO.unlink()
        r.comprobar_estado()
        self.assertFalse((self.op / 'inventario.jsonl').exists())
        (self.op / 'finalizada-v1.json').unlink()
        with self.assertRaises(RuntimeError): r.comprobar_estado()

    def test_recursos_y_padres_contradictorios(self):
        with patch.dict(os.environ, {'GESTOR_INVENTARIO_MAX_ENTRADAS': '1'}):
            with self.assertRaises(ValueError): inv.verificar(self.op, self.datos['inventario'])
        for valor in ('0', '-1', 'invalido'):
            with patch.dict(os.environ, {'GESTOR_INVENTARIO_MAX_BYTES': valor}):
                with self.assertRaises(ValueError): inv.Presupuesto()
        archivo = self.op / 'inventario.jsonl'
        filas = [json.loads(l) for l in archivo.read_text().splitlines()]
        filas[0]['ruta'] = '../fuera'
        with self.assertRaises(ValueError): inv.validar_fila(filas[0])
        presupuesto = inv.Presupuesto(); presupuesto.fin = 0
        with self.assertRaises(ValueError): inv.huella(inv.DB_PATH, presupuesto)
        filas = [json.loads(l) for l in archivo.read_text().splitlines()]
        filas = [f for f in filas if not (f['conjunto'] == 'anterior' and f['ruta'] == 'storage')]
        contenido = ''.join(json.dumps(f) + '\n' for f in filas).encode()
        archivo.write_bytes(contenido)
        descriptor = {'sha256': hashlib.sha256(contenido).hexdigest(), 'bytes': len(contenido), 'entradas': len(filas)}
        with self.assertRaises(ValueError): inv.verificar(self.op, descriptor)


if __name__ == '__main__':
    unittest.main(verbosity=2)
