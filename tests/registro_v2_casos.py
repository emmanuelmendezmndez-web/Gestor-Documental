"""Esquemas e inventarios con archivos ficticios; no restaura bases de datos."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

from aislamiento import exigir_directorio_temporal
PADRE = exigir_directorio_temporal("siged-prueba-registro-v2-")
from app import registro_restauracion as r
from app import inventario_restauracion as inv
from app import coordinacion as coord
from app import diagnostico_restauracion as diag
from app import seleccion_originales as sel


class EsquemaTest(unittest.TestCase):
    def test_cierre_reanuda_y_permanece_valido_tras_uso(self):
        self._base_local_recuperacion()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            with patch.object(r.os, 'replace', side_effect=PermissionError):
                self.assertEqual(coord.finalizar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertTrue((self.op / 'finalizada.json').exists())
            self.assertNotEqual(r.leer(r.REGISTRO)['estado'], 'finalizada')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            informe = coord.finalizar_recuperacion(self.op.name, self.op.name)
            self.assertEqual(informe['estado'], 'restauración finalizada', informe)
            self.assertTrue(informe['listo_recuperacion'])
            with coord.BloqueoDatos(False): pass
            with patch.dict(os.environ, {'GESTOR_SECRET_KEY': 'otro-valor-ficticio'}):
                with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            clave_apartada = self.root / 'clave-apartada-ficticia'
            inv.SECRET_PATH.rename(clave_apartada)
            try:
                with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            finally:
                clave_apartada.rename(inv.SECRET_PATH)
            self.assertEqual(coord.finalizar_recuperacion(self.op.name, self.op.name)['estado'], 'restauración ya finalizada')
            with sqlite3.connect(inv.DB_PATH) as db:
                db.execute("INSERT INTO documentos VALUES(2,'documento.txt',8)")
            db.close()
            (inv.STORAGE_DIR / 'nuevo.txt').write_bytes(b'cambio legitimo ficticio')
            with coord.BloqueoDatos(False): pass
            marca = self.op / 'cierre-recuperacion.json'
            guardada = marca.read_bytes(); marca.write_bytes(b'{')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            marca.write_bytes(guardada)
            with coord.BloqueoDatos(False): pass
            from app import preparacion_persistente as pp
            constancia = self.root / pp._nombre(self.op.name) / 'constancia-preparacion.json'
            guardada_constancia = constancia.read_bytes()
            alterada = json.loads(guardada_constancia)
            alterada['sqlite_transformada']['sha256'] = 'f' * 64
            constancia.write_text(json.dumps(alterada), encoding='utf-8')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            constancia.write_bytes(guardada_constancia)
            with coord.BloqueoDatos(False): pass
            from app import desplazamiento_original as des
            conservacion = self.root / des._nombre(self.op.name)
            apartada = self.root / 'conservacion-apartada-ficticia'
            conservacion.rename(apartada)
            try:
                with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            finally:
                apartada.rename(conservacion)
            with coord.BloqueoDatos(False): pass
            nueva = self.root / '.siged-restauraciones' / 'operacion-ijklmnop'
            nueva.mkdir()
            import shutil
            shutil.copyfile(self.op / 'inventario.jsonl', nueva / 'inventario.jsonl')
            otra = dict(self.datos, operacion=nueva.name, directorio=str(nueva), estado='iniciada', paso='preparada')
            r.escribir(otra)
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_cierre_rechaza_documento_alterado(self):
        self._base_local_recuperacion()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')
            (inv.STORAGE_DIR / 'documento.txt').write_bytes(b'alterado')
            self.assertEqual(coord.finalizar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_cierre_no_acepta_final_aislado(self):
        self._base_local_recuperacion()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')
            datos = r.leer(r.REGISTRO)
            datos.update(estado='finalizada', paso='verificada')
            r.escribir(datos)
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_cierre_no_acepta_final_sin_aplicacion(self):
        self._base_local_recuperacion()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            datos = r.leer(r.REGISTRO)
            datos.update(estado='finalizada', paso='verificada')
            r.escribir(datos)
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_cierre_permite_login_y_operacion_normal(self):
        inv.DB_PATH.unlink()
        env = os.environ.copy(); env['GESTOR_DATA_DIR'] = str(self.root); env['GESTOR_SECRET_KEY'] = ''
        preparar = '''
from app.database import inicializar_db, conectar
from app.seguridad import hashear_password
inicializar_db()
with conectar() as db:
    db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES(?,?,?,?,?)",
               ('adminficticio','Administrador',hashear_password('ClaveFicticia123!'),'admin','Tesoreria'))
'''
        subprocess.run([sys.executable, '-c', preparar], env=env, check=True, timeout=60)
        inv.SECRET_PATH.write_text('clave-local-ficticia-123456789', encoding='utf-8')
        (self.op / 'inventario.jsonl').unlink()
        self.datos['clave_origen'] = 'archivo'
        self.datos['pasos'] = r.CAMBIOS[:]
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')
            resultado = coord.finalizar_recuperacion(self.op.name, self.op.name)
            self.assertEqual(resultado['estado'], 'restauración finalizada', resultado)
            comprobar = '''
import re
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, base_url='http://testserver') as cliente:
    pagina = cliente.get('/login')
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', pagina.text).group(1)
    respuesta = cliente.post('/login', data={'usuario':'adminficticio','password':'ClaveFicticia123!','csrf_token':token}, headers={'Origin':'http://testserver'}, follow_redirects=False)
    assert respuesta.status_code == 303, respuesta.status_code
    pagina = cliente.get('/inicio')
    assert pagina.status_code == 200, pagina.status_code
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', pagina.text).group(1)
    respuesta = cliente.post('/expedientes', data={'titulo':'Expediente ficticio','csrf_token':token}, headers={'Origin':'http://testserver'}, follow_redirects=False)
    assert respuesta.status_code == 303, respuesta.status_code
'''
            proceso = subprocess.run([sys.executable, '-c', comprobar], env=env, capture_output=True, text=True, timeout=90)
            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            with coord.BloqueoDatos(False): pass

    def test_cierre_rechaza_sqlite_alterada_y_recuperacion_parcial(self):
        from app import desplazamiento_original as des
        self._base_local_recuperacion()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            publicar = des._publicar
            def corte(path, datos):
                if path.name == 'confirmacion-instalar-base.json': raise KeyboardInterrupt
                return publicar(path, datos)
            with patch.object(des, '_publicar', side_effect=corte):
                self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertEqual(coord.finalizar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')
            with patch.dict(os.environ, {'GESTOR_SECRET_KEY': 'valor-ficticio-no-acreditado'}):
                self.assertEqual(coord.finalizar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            with sqlite3.connect(inv.DB_PATH) as db:
                db.execute("INSERT INTO documentos VALUES(2, 'documento.txt', 8)")
            db.close()
            self.assertEqual(coord.finalizar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def _base_local_recuperacion(self):
        self._base_para_preparacion()
        inv.SECRET_PATH.write_text('clave-ficticia', encoding='utf-8')
        (self.op / 'inventario.jsonl').unlink()
        self.datos['clave_origen'] = 'archivo'
        self.datos['pasos'] = r.CAMBIOS[:]
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.REGISTRO.unlink()
        (self.op / 'inicio.json').unlink()
        r.escribir(self.datos)

    def test_recuperacion_reanuda_tras_instalar(self):
        from app import desplazamiento_original as des
        from app import preparacion_persistente as pp
        self._base_local_recuperacion()
        anterior = inv.DB_PATH.read_bytes()
        documento = (inv.STORAGE_DIR / 'documento.txt').read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            preparada = self.root / pp._nombre(self.op.name)
            preparado_antes = {str(p.relative_to(preparada)): p.read_bytes() for p in preparada.rglob('*') if p.is_file()}
            publicar = des._publicar
            def interrumpir(path, datos):
                if path.name == 'confirmacion-instalar-base.json': raise KeyboardInterrupt
                return publicar(path, datos)
            with patch.object(des, '_publicar', side_effect=interrumpir):
                informe = coord.aplicar_recuperacion(self.op.name, self.op.name)
            self.assertEqual(informe['estado'], 'bloqueada')
            self.assertFalse(informe['listo_recuperacion'])
            self.assertEqual(inv.DB_PATH.read_bytes(), (preparada / 'base-candidata').read_bytes())
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            env = os.environ.copy(); env['GESTOR_DATA_DIR'] = str(self.root); env['GESTOR_SECRET_KEY'] = ''
            proceso = subprocess.run([sys.executable, '-m', 'app.recuperacion_administrativa', 'aplicar', '--operacion', self.op.name,
                                      '--confirmar-operacion', self.op.name], env=env, capture_output=True, text=True, timeout=100)
            self.assertEqual(proceso.returncode, 0, proceso.stderr + proceso.stdout)
            self.assertFalse(json.loads(proceso.stdout)['listo_recuperacion'])
            root = self.root / des._nombre(self.op.name)
            self.assertEqual((root / 'base').read_bytes(), anterior)
            self.assertEqual((root / 'storage' / 'documento.txt').read_bytes(), documento)
            self.assertEqual((root / 'clave').read_text(), 'clave-ficticia')
            self.assertEqual((inv.STORAGE_DIR / 'documento.txt').read_bytes(), documento)
            with sqlite3.connect(inv.DB_PATH) as db:
                self.assertEqual(db.execute('SELECT estado FROM eliminaciones_pendientes').fetchone()[0], 'suspendida')
            db.close()
            preparado_despues = {str(p.relative_to(preparada)): p.read_bytes() for p in preparada.rglob('*') if p.is_file()}
            self.assertEqual(preparado_antes, preparado_despues)
            instalado = inv.DB_PATH.read_bytes()
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')
            self.assertEqual(inv.DB_PATH.read_bytes(), instalado)
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_recuperacion_conserva_estado_activo_distinto(self):
        from app import desplazamiento_original as des
        self._base_local_recuperacion()
        original = inv.DB_PATH.read_bytes()
        inv.DB_PATH.rename(self.op / 'anterior-base')
        inv.DB_PATH.write_bytes(b'estado-activo-ficticio')
        self.datos.update(estado='pendiente', paso='base-guardar')
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            publicar = des._publicar
            def corte(path, datos):
                if path.name == 'confirmacion-conservar-activo-base.json': raise KeyboardInterrupt
                return publicar(path, datos)
            with patch.object(des, '_publicar', side_effect=corte):
                self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            root = self.root / des._nombre(self.op.name)
            self.assertFalse(inv.DB_PATH.exists())
            self.assertEqual((root / 'previo-activo-base').read_bytes(), b'estado-activo-ficticio')
            resultado = coord.aplicar_recuperacion(self.op.name, self.op.name)
            self.assertEqual(resultado['estado'], 'instalación verificada; arranque bloqueado', resultado)
            self.assertEqual((root / 'base').read_bytes(), original)
            self.assertEqual((root / 'previo-activo-base').read_bytes(), b'estado-activo-ficticio')
            self.assertFalse(resultado['listo_recuperacion'])

    def test_recuperacion_corte_antes_del_primer_movimiento(self):
        from app import desplazamiento_original as des
        self._base_local_recuperacion()
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            with coord._BloqueoSistema(exclusivo=False):
                with self.assertRaises(coord.BloqueoNoDisponible):
                    coord.aplicar_recuperacion(self.op.name, self.op.name)
                env = os.environ.copy(); env['GESTOR_DATA_DIR'] = str(self.root)
                proceso = subprocess.run([sys.executable, '-m', 'app.recuperacion_administrativa', 'aplicar',
                                          '--operacion', self.op.name, '--confirmar-operacion', self.op.name],
                                         env=env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(proceso.returncode, 0)
                self.assertEqual(json.loads(proceso.stdout)['estado'], 'bloqueada')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            with patch.object(des, '_operar', side_effect=KeyboardInterrupt):
                self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_recuperacion_rechaza_etapa_manipulada(self):
        from app import desplazamiento_original as des
        self._base_local_recuperacion()
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            with patch.object(des, '_operar', side_effect=KeyboardInterrupt):
                self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            root = self.root / des._nombre(self.op.name)
            plan = des._leer(root / 'instalacion.json')
            (root / plan['etapa'] / 'base').write_bytes(b'manipulacion ficticia')
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            self.assertFalse((root / 'base').exists())
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_recuperacion_rechaza_preparacion_y_clave_inciertas(self):
        from app import preparacion_persistente as pp
        self._base_para_preparacion()  # Procedencia de entorno no acreditada.
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertEqual(coord.finalizar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            root = self.root / pp._nombre(self.op.name)
            (root / 'storage' / 'documento.txt').unlink()
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            self.assertEqual((inv.STORAGE_DIR / 'documento.txt').read_bytes(), b'anterior')

    def test_recuperacion_cortes_en_cada_instalacion(self):
        from app import desplazamiento_original as des
        self._base_local_recuperacion()
        publicar = des._publicar
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            for nombre in ('base', 'storage', 'clave'):
                def corte(path, datos):
                    if path.name == 'confirmacion-instalar-' + nombre + '.json': raise KeyboardInterrupt
                    return publicar(path, datos)
                with patch.object(des, '_publicar', side_effect=corte):
                    resultado = coord.aplicar_recuperacion(self.op.name, self.op.name)
                self.assertEqual(resultado['estado'], 'bloqueada')
                self.assertFalse(resultado['listo_recuperacion'])
                with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')

    def test_recuperacion_con_desplazamiento_previo(self):
        from app import desplazamiento_original as des
        self._base_local_recuperacion()
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'base')['estado'], 'desplazado confirmado')
            resultado = coord.aplicar_recuperacion(self.op.name, self.op.name)
            self.assertEqual(resultado['estado'], 'instalación verificada; arranque bloqueado', resultado)
            self.assertEqual((self.root / des._nombre(self.op.name) / 'base').read_bytes(), original)
            self.assertFalse(resultado['listo_recuperacion'])

    def test_recuperacion_espacio_y_movimiento_denegado(self):
        from app import desplazamiento_original as des
        from app import instalacion_recuperacion as instalacion
        self._base_local_recuperacion()
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            with patch.object(instalacion.shutil, 'disk_usage', return_value=type('Uso', (), {'free': 0})()):
                self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            with patch.object(instalacion, '_mover', side_effect=PermissionError):
                self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'bloqueada')
            root = self.root / des._nombre(self.op.name)
            self.assertEqual((root / 'base').read_bytes(), original)
            self.assertEqual(coord.aplicar_recuperacion(self.op.name, self.op.name)['estado'], 'instalación verificada; arranque bloqueado')

    def test_recuperacion_limite_antes_de_leer_archivo(self):
        from app import instalacion_recuperacion as instalacion
        archivo = self.root / 'archivo-ficticio'
        archivo.write_bytes(b'12345678')
        with patch.dict(os.environ, {'GESTOR_VERIFICACION_MAX_BYTES': '1'}), patch.object(inv, 'huella', side_effect=AssertionError('no debe leer')):
            with self.assertRaises(ValueError): instalacion._huella(archivo, 'base')
        self.assertEqual(archivo.read_bytes(), b'12345678')

    def test_desplazamiento_desde_original_guardado(self):
        from app import desplazamiento_original as desplazamiento
        self._base_para_preparacion()
        original = inv.DB_PATH.read_bytes()
        guardada = self.op / 'anterior-base'
        inv.DB_PATH.rename(guardada)
        self.datos.update(estado='pendiente', paso='base-guardar')
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'base')['estado'], 'desplazado confirmado')
            self.assertFalse(guardada.exists())
            conservada = self.root / desplazamiento._nombre(self.op.name) / 'base'
            self.assertEqual(conservada.read_bytes(), original)
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'desplazado confirmado')
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)

    def test_desplazamiento_reanuda_tras_movimiento(self):
        from app import desplazamiento_original as desplazamiento
        self._base_para_preparacion()
        original = inv.DB_PATH.read_bytes()
        documento = (inv.STORAGE_DIR / 'documento.txt').read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            antes_registro = r.REGISTRO.read_bytes()
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'en origen')
            publicar = desplazamiento._publicar
            def cortar(path, datos):
                if path.name == 'confirmacion-base.json': raise KeyboardInterrupt
                return publicar(path, datos)
            with patch.object(desplazamiento, '_publicar', side_effect=cortar):
                interrumpida = coord.desplazar_original(self.op.name, self.op.name, 'base')
            self.assertEqual(interrumpida['estado'], 'no verificable')
            root = self.root / desplazamiento._nombre(self.op.name)
            self.assertFalse(inv.DB_PATH.exists())
            self.assertEqual((root / 'base').read_bytes(), original)
            self.assertTrue((root / 'intencion-base.json').is_file())
            self.assertFalse((root / 'confirmacion-base.json').exists())
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'desplazado sin confirmación')
            env = os.environ.copy(); env['GESTOR_DATA_DIR'] = str(self.root)
            proceso = subprocess.run([sys.executable, '-m', 'app.desplazamiento_original', 'desplazar', '--operacion', self.op.name,
                                     '--confirmar-operacion', self.op.name, '--componente', 'base'],
                                    env=env, capture_output=True, text=True, timeout=40)
            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            self.assertEqual(json.loads(proceso.stdout)['estado'], 'desplazado confirmado')
            self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'base')['estado'], 'desplazado confirmado')
            self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'storage')['estado'], 'desplazado confirmado')
            self.assertEqual((root / 'storage' / 'documento.txt').read_bytes(), documento)
            self.assertEqual(r.REGISTRO.read_bytes(), antes_registro)
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            self.assertFalse(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['listo_recuperacion'])

    def test_desplazamiento_rechaza_destino_y_alteracion(self):
        from app import desplazamiento_original as desplazamiento
        self._base_para_preparacion()
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            self.assertEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            with patch.dict(os.environ, {'GESTOR_SELECCION_MAX_BYTES': '1'}):
                self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            self.assertFalse((self.root / desplazamiento._nombre(self.op.name)).exists())
            self.assertEqual(coord.desplazar_original(self.op.name, 'incorrecta', 'base')['estado'], 'no verificable')
            with patch.object(desplazamiento.os, 'rename', side_effect=PermissionError):
                self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            root = self.root / desplazamiento._nombre(self.op.name)
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            intencion = root / 'intencion-base.json'
            contenido = intencion.read_bytes()
            intencion.write_bytes(b'{')
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            contradictoria = json.loads(contenido); contradictoria['componente'] = 'storage'
            intencion.write_text(json.dumps(contradictoria), encoding='utf-8')
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            contradictoria = json.loads(contenido); contradictoria['version'] = True
            intencion.write_text(json.dumps(contradictoria), encoding='utf-8')
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            intencion.write_bytes(contenido)
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'en origen')
            identidad_duplicada = self.op / 'anterior-base'
            os.link(inv.DB_PATH, identidad_duplicada)
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            identidad_duplicada.unlink()
            with coord._BloqueoSistema(exclusivo=True):
                with self.assertRaises(coord.BloqueoNoDisponible):
                    coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')
            (root / 'base').write_bytes(b'ocupado')
            self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            self.assertEqual((root / 'base').read_bytes(), b'ocupado')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            (root / 'base').unlink()
            self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'base')['estado'], 'desplazado confirmado')
            extraviado = root / 'base-ficticia-apartada'
            (root / 'base').rename(extraviado)
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            extraviado.rename(root / 'base')
            (root / 'base').write_bytes(b'alterado')
            self.assertEqual(coord.inspeccionar_desplazamiento(self.op.name, self.op.name, 'base')['estado'], 'no verificable')
            with coord._BloqueoSistema(exclusivo=True): pass

    def _base_para_preparacion(self):
        inv.DB_PATH.unlink()
        with sqlite3.connect(inv.DB_PATH) as db:
            db.executescript('''
                CREATE TABLE documentos(id INTEGER PRIMARY KEY, nombre_guardado TEXT, tamano_bytes INTEGER);
                INSERT INTO documentos VALUES(1, 'documento.txt', 8);
                CREATE TABLE eliminaciones_pendientes(id INTEGER PRIMARY KEY, tipo TEXT, nombre TEXT, identidad TEXT, estado TEXT, intentos INTEGER, ultimo_error TEXT, creado_en TEXT);
                INSERT INTO eliminaciones_pendientes VALUES(1,'documento','documento.txt','x','pendiente',0,'','hoy');
            ''')
        db.close()
        (self.op / 'inventario.jsonl').unlink()
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.escribir(self.datos)

    def test_preparacion_persistente_y_nuevo_proceso(self):
        from app import preparacion_persistente as pp
        self._base_para_preparacion()
        original = inv.DB_PATH.read_bytes()
        documentos = (inv.STORAGE_DIR / 'documento.txt').read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            resultado = coord.preparar_persistente()
            self.assertEqual(resultado['estado'], 'preparación íntegra', resultado)
            self.assertFalse(resultado['listo_recuperacion'])
            root = self.root / pp._nombre(self.op.name)
            self.assertTrue((root / 'constancia-preparacion.json').is_file())
            self.assertEqual((root / 'base').read_bytes(), original)
            self.assertNotEqual((root / 'base-candidata').read_bytes(), original)
            self.assertEqual((root / 'storage' / 'documento.txt').read_bytes(), documentos)
            with sqlite3.connect(root / 'base-candidata') as db:
                self.assertEqual(db.execute('SELECT estado FROM eliminaciones_pendientes').fetchone()[0], 'suspendida')
            db.close()
            antes = (root / 'constancia-preparacion.json').read_bytes()
            self.assertNotEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual((root / 'constancia-preparacion.json').read_bytes(), antes)
            env = os.environ.copy(); env['GESTOR_DATA_DIR'] = str(self.root)
            proceso = subprocess.run([sys.executable, '-m', 'app.preparacion_persistente'], env=env, capture_output=True, text=True, timeout=40)
            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            self.assertEqual(json.loads(proceso.stdout)['estado'], 'preparación íntegra')
            antes_registro = r.REGISTRO.read_bytes()
            informe = coord.comprobar_recuperacion(self.op.name, self.op.name)
            self.assertEqual(informe['estado'], 'bloqueada')
            self.assertIn('no se ha acreditado', informe['motivo'].lower())
            self.assertFalse(informe['listo_recuperacion'])
            self.assertEqual(r.REGISTRO.read_bytes(), antes_registro)
            self.assertEqual((root / 'constancia-preparacion.json').read_bytes(), antes)
            with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            with patch.object(pp, 'verificar_acl_privada', side_effect=PermissionError):
                self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'no verificable')
            constancia = root / 'constancia-preparacion.json'
            alterada = json.loads(antes); alterada['operacion'] = 'operacion-zzzzzzzz'
            constancia.write_text(json.dumps(alterada), encoding='utf-8')
            self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'contradictoria')
            alterada = json.loads(antes); alterada['tareas_suspendidas'] += 1
            constancia.write_text(json.dumps(alterada), encoding='utf-8')
            self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'contradictoria')
            constancia.write_bytes(antes)
            extra = root / 'inesperado'; extra.write_bytes(b'ficticio')
            self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'contradictoria')
            extra.unlink()
            faltante = root / 'storage' / 'documento.txt'
            guardado = root / 'documento-guardado'
            faltante.rename(guardado)
            self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'contradictoria')
            guardado.rename(faltante)
            (root / 'storage' / 'documento.txt').write_bytes(b'modificado')
            self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'contradictoria')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            self.assertEqual((inv.STORAGE_DIR / 'documento.txt').read_bytes(), documentos)

    def test_preparacion_finalizada_antes_de_interrupcion(self):
        from app import preparacion_persistente as pp
        from app import constancia_preparacion as cp
        self._base_para_preparacion()
        original = inv.DB_PATH.read_bytes()
        publicar = cp.publicar
        def interrumpir(*args):
            publicar(*args)
            raise KeyboardInterrupt
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            with patch.object(cp, 'publicar', side_effect=interrumpir):
                self.assertNotEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'preparación íntegra')
            self.assertFalse(coord.inspeccionar_preparacion()['listo_recuperacion'])
            self.assertEqual(inv.DB_PATH.read_bytes(), original)

    def test_preparacion_rechaza_espacio_y_permisos(self):
        from app import verificacion_originales as ver
        from app import temporal_privado as privado
        self._base_para_preparacion()
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            with patch.object(ver.shutil, 'disk_usage', return_value=type('Uso', (), {'free': 0})()):
                self.assertEqual(coord.preparar_persistente()['estado'], 'verificación incompleta')
            with patch.object(privado, '_volumen_acl', side_effect=PermissionError):
                self.assertEqual(coord.preparar_persistente()['estado'], 'verificación incompleta')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)
            self.assertFalse(list(self.root.glob('.siged-preparacion-*')))

    def test_preparacion_clave_local_y_entorno_cambiado(self):
        from app import constancia_preparacion as cp
        from app import preparacion_persistente as pp
        self._base_para_preparacion()
        inv.SECRET_PATH.write_text('clave-ficticia', encoding='utf-8')
        (self.op / 'inventario.jsonl').unlink()
        self.datos['clave_origen'] = 'archivo'
        self.datos['pasos'] = r.CAMBIOS[:]
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.REGISTRO.unlink()
        (self.op / 'inicio.json').unlink()
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH), patch.dict(os.environ, {'GESTOR_SECRET_KEY': ''}):
            resultado = coord.preparar_persistente()
            self.assertEqual(resultado['estado'], 'preparación íntegra', resultado)
            root = self.root / pp._nombre(self.op.name)
            self.assertEqual(cp.leer(root)['clave'], 'archivo identificado')
            self.assertNotIn('clave-ficticia', (root / 'constancia-preparacion.json').read_text())
            antes = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            self.assertIn('confirmación', coord.comprobar_recuperacion(self.op.name, 'incorrecta')['motivo'])
            selector = sel._seleccionar
            def bajo_exclusivo(*args):
                with self.assertRaises(coord.BloqueoNoDisponible): coord._BloqueoSistema(exclusivo=True)
                return selector(*args)
            with patch.object(sel, '_seleccionar', side_effect=bajo_exclusivo):
                informe = coord.comprobar_recuperacion(self.op.name, self.op.name)
            self.assertEqual(informe['estado'], 'bloqueada')
            self.assertFalse(informe['listo_recuperacion'])
            self.assertIn('no autoriza', informe['motivo'])
            despues = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            self.assertEqual(antes, despues)
            original_desplazado = self.root / 'base-desplazada-ficticia'
            inv.DB_PATH.rename(original_desplazado)
            try:
                self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'no verificable')
                with self.assertRaises(RuntimeError): coord.BloqueoDatos(False)
            finally:
                original_desplazado.rename(inv.DB_PATH)
            with patch.dict(os.environ, {'GESTOR_SECRET_KEY': 'otra-clave-ficticia'}):
                informe = coord.inspeccionar_preparacion()
                self.assertIn('incompatible', informe['clave'])
                self.assertFalse(informe['listo_recuperacion'])
            self.assertEqual(inv.SECRET_PATH.read_text(), 'clave-ficticia')
            from app import desplazamiento_original as desplazamiento
            self.assertEqual(coord.desplazar_original(self.op.name, self.op.name, 'clave')['estado'], 'desplazado confirmado')
            self.assertFalse(inv.SECRET_PATH.exists())
            self.assertEqual((self.root / desplazamiento._nombre(self.op.name) / 'clave').read_text(), 'clave-ficticia')

    def test_preparacion_interrumpida_conserva_evidencia(self):
        from app import preparacion_persistente as pp
        self._base_para_preparacion()
        original = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            with patch.object(pp, 'publicar', side_effect=KeyboardInterrupt):
                self.assertNotEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            root = self.root / pp._nombre(self.op.name)
            self.assertTrue((root / 'base').exists())
            self.assertFalse((root / 'constancia-preparacion.json').exists())
            self.assertEqual(coord.inspeccionar_preparacion()['estado'], 'incompleta')
            self.assertNotEqual(coord.preparar_persistente()['estado'], 'preparación íntegra')
            self.assertEqual(inv.DB_PATH.read_bytes(), original)

    def test_constancia_independiente_sin_sobrescritura(self):
        from app import constancia_preparacion as cp
        carpeta = self.root / 'preparacion-ficticia'
        carpeta.mkdir()
        antes = inv.DB_PATH.read_bytes()
        datos = {'version': 1, 'operacion': self.op.name,
                 'inventario_sha256': self.datos['inventario']['sha256'],
                 'sqlite_anterior': {'sha256': 'a' * 64, 'tamano': 123},
                 'sqlite_verificada': {'sha256': 'a' * 64, 'tamano': 123},
                 'sqlite_transformada': {'sha256': 'b' * 64, 'tamano': 123},
                 'tareas_suspendidas': 1, 'clave': 'entorno no acreditado',
                 'listo_recuperacion': False}
        cp.publicar(carpeta, datos)
        self.assertEqual(cp.leer(carpeta), datos)
        contenido = (carpeta / 'constancia-preparacion.json').read_bytes()
        with self.assertRaises(FileExistsError):
            cp.publicar(carpeta, datos)
        self.assertEqual((carpeta / 'constancia-preparacion.json').read_bytes(), contenido)
        self.assertFalse(list(carpeta.glob('*.tmp')))
        for incorrecto in ({**datos, 'listo_recuperacion': True},
                           {**datos, 'sqlite_verificada': {'sha256': 'c' * 64, 'tamano': 123}},
                           {**datos, 'clave': 'verificada'}):
            with self.assertRaises(ValueError): cp.validar(incorrecto)
        path = carpeta / 'constancia-preparacion.json'
        for texto in (b'{', b'{"version":1,"version":1}'):
            path.write_bytes(texto)
            with self.assertRaises(ValueError): cp.leer(carpeta)
        self.assertEqual(inv.DB_PATH.read_bytes(), antes)

    def test_constancia_publicacion_interrumpida(self):
        from app import constancia_preparacion as cp
        carpeta = self.root / 'preparacion-ficticia'
        carpeta.mkdir()
        datos = {'version': 1, 'operacion': self.op.name,
                 'inventario_sha256': self.datos['inventario']['sha256'],
                 'sqlite_anterior': {'sha256': 'a' * 64, 'tamano': 1},
                 'sqlite_verificada': {'sha256': 'a' * 64, 'tamano': 1},
                 'sqlite_transformada': {'sha256': 'b' * 64, 'tamano': 1},
                 'tareas_suspendidas': 0, 'clave': 'evidencia insuficiente',
                 'listo_recuperacion': False}
        with patch.object(cp.os, 'link', side_effect=OSError('fallo simulado')):
            with self.assertRaises(OSError): cp.publicar(carpeta, datos)
        self.assertEqual(list(carpeta.iterdir()), [])
        with self.assertRaises(FileNotFoundError): cp.leer(carpeta)

    def test_preparacion_cola_y_clave_sin_autorizar(self):
        from app import preparacion_cola as prep
        inv.DB_PATH.unlink()
        with sqlite3.connect(inv.DB_PATH) as db:
            db.executescript('''
                CREATE TABLE documentos(id INTEGER PRIMARY KEY, nombre_guardado TEXT, tamano_bytes INTEGER);
                INSERT INTO documentos VALUES(1, 'documento.txt', 8);
                CREATE TABLE eliminaciones_pendientes(id INTEGER PRIMARY KEY, tipo TEXT, nombre TEXT, identidad TEXT, estado TEXT, intentos INTEGER, ultimo_error TEXT, creado_en TEXT);
                INSERT INTO eliminaciones_pendientes VALUES(1,'documento','documento.txt','x','pendiente',0,'','hoy');
                INSERT INTO eliminaciones_pendientes VALUES(2,'documento','otro.txt','x','suspendida',1,'previo','hoy');
            ''')
        db.close()
        (self.op / 'inventario.jsonl').unlink()
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.escribir(self.datos)
        antes = inv.DB_PATH.read_bytes()
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            with patch.dict(os.environ, {'GESTOR_SECRET_KEY': 'ficticia-distinta'}):
                resultado = coord.preparar_cola_aislada()
            self.assertEqual(resultado['estado'], 'copia verificada', resultado)
            self.assertFalse(resultado['listo_recuperacion'])
            p = resultado['preparacion_temporal']
            self.assertEqual(p['clave'], 'entorno histórico no verificable')
            self.assertEqual((p['total_tareas'], p['tareas_suspendidas']), (2, 1))
            self.assertNotEqual(p['sha256_antes'], p['sha256_despues'])
            self.assertEqual(p['sha256_antes'], hashlib.sha256(antes).hexdigest())
            self.assertEqual(inv.DB_PATH.read_bytes(), antes)
            self.assertEqual((inv.STORAGE_DIR / 'documento.txt').read_bytes(), b'anterior')
            self.assertFalse(list(self.root.glob('.siged-verificacion-*')))
        evidencia = {'registro': {'clave_origen': 'archivo'}, 'entradas': {'clave': {'tipo': 'archivo'}}}
        self.assertIn('identificado', prep.evaluar_clave(evidencia, False))
        self.assertIn('incompatible', prep.evaluar_clave(evidencia, True))
        evidencia['entradas']['clave']['tipo'] = 'ausente'
        self.assertEqual(prep.evaluar_clave(evidencia, False), 'evidencia insuficiente')

    def test_preparacion_revierte_fallo(self):
        from app import preparacion_cola as prep
        anterior = self.root / 'anterior.db'
        candidata = self.root / 'candidata.db'
        with sqlite3.connect(anterior) as db:
            db.executescript("CREATE TABLE eliminaciones_pendientes(id INTEGER, tipo TEXT, nombre TEXT, identidad TEXT, estado TEXT, intentos INTEGER, ultimo_error TEXT, creado_en TEXT); INSERT INTO eliminaciones_pendientes VALUES(1,'documento','a','x','pendiente',0,'','hoy');")
        db.close()
        antes = anterior.read_bytes()
        original = prep._resumen
        def fallo(*args, **kwargs):
            if not kwargs and len(args) == 2:
                raise ValueError('fallo simulado')
            return original(*args, **kwargs)
        with patch.object(prep, '_resumen', side_effect=fallo), self.assertRaises(ValueError):
            prep.transformar_copia(anterior, candidata, inv.Presupuesto())
        with sqlite3.connect(candidata) as db:
            self.assertEqual(db.execute('SELECT estado FROM eliminaciones_pendientes').fetchone()[0], 'pendiente')
        db.close()
        self.assertEqual(anterior.read_bytes(), antes)
        interrumpida = self.root / 'interrumpida.db'
        with patch.object(prep, '_resumen', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            prep.transformar_copia(anterior, interrumpida, inv.Presupuesto())
        with sqlite3.connect(interrumpida) as db:
            self.assertEqual(db.execute('SELECT estado FROM eliminaciones_pendientes').fetchone()[0], 'pendiente')
        db.close()
        self.assertEqual(anterior.read_bytes(), antes)

    def test_preparacion_rechaza_auxiliares(self):
        from app import preparacion_cola as prep
        anterior = self.root / 'anterior.db'
        candidata = self.root / 'candidata.db'
        anterior.write_bytes(b'base ficticia')
        for base in (anterior, candidata):
            for sufijo in ('-wal', '-shm', '-journal'):
                auxiliar = base.with_name(base.name + sufijo)
                auxiliar.write_bytes(b'auxiliar ficticio')
                with self.assertRaises(ValueError):
                    prep.transformar_copia(anterior, candidata, inv.Presupuesto())
                self.assertEqual(auxiliar.read_bytes(), b'auxiliar ficticio')
                self.assertEqual(anterior.read_bytes(), b'base ficticia')
                self.assertFalse(candidata.exists())
                auxiliar.unlink()
        anterior.unlink()
        with sqlite3.connect(anterior) as db:
            db.execute('CREATE TABLE eliminaciones_pendientes(id INTEGER, tipo TEXT, nombre TEXT, identidad TEXT, estado TEXT, intentos INTEGER, ultimo_error TEXT, creado_en TEXT)')
        db.close()
        original = prep._comprobar_auxiliares
        llamadas = []
        def simular_auxiliar(base):
            llamadas.append(base)
            if len(llamadas) == 4:
                base.with_name(base.name + '-wal').write_bytes(b'auxiliar ficticio')
            return original(base)
        with patch.object(prep, '_comprobar_auxiliares', side_effect=simular_auxiliar), self.assertRaises(ValueError):
            prep.transformar_copia(anterior, candidata, inv.Presupuesto())
        self.assertEqual(len(llamadas), 4)
        self.assertEqual(candidata.with_name(candidata.name + '-wal').read_bytes(), b'auxiliar ficticio')

    def test_copia_sqlite_valida_y_fallos_controlados(self):
        inv.DB_PATH.unlink()
        with sqlite3.connect(inv.DB_PATH) as db:
            db.execute('CREATE TABLE documentos(id INTEGER PRIMARY KEY, nombre_guardado TEXT, tamano_bytes INTEGER, eliminado_en TEXT)')
            db.execute("INSERT INTO documentos VALUES(1,'documento.txt',8,'2026-01-01')")
        db.close()
        (self.op / 'inventario.jsonl').unlink()
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            antes = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            from app import verificacion_originales as ver
            sincronizar = ver.os.fsync
            seleccionar = sel._seleccionar
            def bajo_bloqueo(*args):
                with self.assertRaises(coord.BloqueoNoDisponible):
                    coord._BloqueoSistema(exclusivo=True)
                return seleccionar(*args)
            def copia_bajo_bloqueo(fd):
                with self.assertRaises(coord.BloqueoNoDisponible):
                    coord._BloqueoSistema(exclusivo=True)
                return sincronizar(fd)
            with patch.object(sel, '_seleccionar', side_effect=bajo_bloqueo) as llamadas, patch.object(ver.os, 'fsync', side_effect=copia_bajo_bloqueo):
                resultado = coord.verificar_originales_aislados()
            self.assertEqual(llamadas.call_count, 2)
            self.assertEqual(resultado['estado'], 'copia verificada', resultado)
            self.assertFalse(resultado['listo_recuperacion'])
            despues = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.name != '.siged-coordinacion.lock'}
            self.assertEqual(antes, despues)
            with patch.dict(os.environ, {'GESTOR_VERIFICACION_MAX_BYTES': '1'}):
                self.assertEqual(coord.verificar_originales_aislados()['estado'], 'verificación incompleta')
            with patch.object(ver.shutil, 'disk_usage', return_value=type('Uso', (), {'free': 0})()):
                self.assertEqual(coord.verificar_originales_aislados()['estado'], 'verificación incompleta')
            with patch.object(ver.os, 'fsync', side_effect=PermissionError):
                self.assertEqual(coord.verificar_originales_aislados()['estado'], 'verificación incompleta')
            with patch.object(ver.os, 'fsync', side_effect=KeyboardInterrupt):
                self.assertEqual(coord.verificar_originales_aislados()['estado'], 'verificación incompleta')
            self.assertEqual(inv.DB_PATH.read_bytes(), antes['gestor.db'])
            self.assertFalse(list(self.root.glob('.siged-verificacion-*')))

    def test_copia_rechaza_referencia_rota(self):
        inv.DB_PATH.unlink()
        with sqlite3.connect(inv.DB_PATH) as db:
            db.execute('CREATE TABLE documentos(id INTEGER PRIMARY KEY, nombre_guardado TEXT, tamano_bytes INTEGER)')
            db.execute("INSERT INTO documentos VALUES(1,'faltante.txt',8)")
        db.close()
        (self.op / 'inventario.jsonl').unlink()
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            antes = inv.DB_PATH.read_bytes()
            self.assertEqual(coord.verificar_originales_aislados()['estado'], 'verificación incompleta')
            self.assertEqual(inv.DB_PATH.read_bytes(), antes)

    def test_copia_rechaza_relaciones_invalidas(self):
        inv.DB_PATH.unlink()
        with sqlite3.connect(inv.DB_PATH) as db:
            db.executescript('''
                CREATE TABLE documentos(id INTEGER PRIMARY KEY, nombre_guardado TEXT, tamano_bytes INTEGER);
                INSERT INTO documentos VALUES(1, 'documento.txt', 8);
                CREATE TABLE expedientes(id INTEGER PRIMARY KEY);
                CREATE TABLE expediente_documentos(expediente_id INTEGER, documento_id INTEGER);
                INSERT INTO expediente_documentos VALUES(99, 1);
            ''')
        db.close()
        (self.op / 'inventario.jsonl').unlink()
        self.datos['inventario'] = inv.publicar(self.op, self.previo)
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            antes = inv.DB_PATH.read_bytes()
            self.assertEqual(coord.verificar_originales_aislados()['estado'], 'verificación incompleta')
            self.assertEqual(inv.DB_PATH.read_bytes(), antes)
            with coord._BloqueoSistema(exclusivo=True):
                pass

    def test_copia_detecta_cambio_durante_lectura(self):
        r.escribir(self.datos)
        from app import verificacion_originales as ver
        documento = inv.STORAGE_DIR / 'documento.txt'
        sincronizar = ver.os.fsync
        def cambiar(fd):
            documento.write_bytes(b'cambio externo simulado')
            return sincronizar(fd)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            with patch.object(ver.os, 'fsync', side_effect=cambiar):
                resultado = coord.verificar_originales_aislados()
            self.assertEqual(resultado['estado'], 'verificación incompleta')
            self.assertFalse(resultado['listo_recuperacion'])
            self.assertEqual(inv.DB_PATH.read_bytes(), b'base anterior ficticia')
            self.assertFalse(list(self.root.glob('.siged-verificacion-*')))

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

    def test_seleccion_originales_completo_y_errores(self):
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            antes = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            informe = coord.seleccionar_originales()
            self.assertEqual(informe['estado'], 'candidato identificado', informe)
            verificacion = coord.verificar_originales_aislados()
            self.assertEqual(verificacion['estado'], 'verificación incompleta')
            self.assertEqual(verificacion['seleccion'], 'candidato identificado')
            self.assertFalse(verificacion['listo_recuperacion'])
            self.assertEqual(informe['clave_efectiva'], 'entorno no verificado')
            self.assertFalse(informe['listo_recuperacion'])
            historica = r.RAIZ / 'operacion-ijklmnop'; historica.mkdir()
            antiguo = {k: v for k, v in self.datos.items() if k in r.BASE}
            antiguo.update(version=1, operacion=historica.name, directorio=str(historica), estado='finalizada', paso='verificada')
            r._inmutable(historica / 'finalizada-v1.json', antiguo)
            self.assertEqual(coord.seleccionar_originales()['estado'], 'candidato identificado')
            (historica / 'finalizada-v1.json').unlink(); historica.rmdir()
            despues = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.name != '.siged-coordinacion.lock'}
            self.assertEqual(antes, despues)
            extra = inv.STORAGE_DIR / 'extra.txt'; extra.write_bytes(b'extra')
            self.assertNotEqual(coord.seleccionar_originales()['estado'], 'candidato identificado')
            extra.unlink()
            with patch.dict(os.environ, {'GESTOR_SELECCION_MAX_BYTES': '1'}):
                self.assertEqual(coord.seleccionar_originales()['estado'], 'evidencia insuficiente')

    def test_seleccion_auxiliar_sqlite(self):
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            auxiliar = inv.DB_PATH.parent / (inv.DB_PATH.name + '-wal')
            auxiliar.write_bytes(b'ficticio')
            self.assertEqual(coord.seleccionar_originales()['estado'], 'evidencia insuficiente')
            self.assertEqual(auxiliar.read_bytes(), b'ficticio')

    def test_verificacion_mantiene_bloqueo_en_seleccion(self):
        r.escribir(self.datos)
        original = sel._seleccionar
        def comprobar(*args):
            with self.assertRaises(coord.BloqueoNoDisponible):
                coord.BloqueoDatos(True)
            return original(*args)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            with patch.object(sel, '_seleccionar', side_effect=comprobar) as seleccion:
                resultado = coord.verificar_originales_aislados()
            self.assertEqual(seleccion.call_count, 1)
            self.assertEqual(resultado['estado'], 'verificación incompleta')
            self.assertFalse(resultado['listo_recuperacion'])
            self.assertEqual(coord.seleccionar_originales()['estado'], 'candidato identificado')

    def test_seleccion_rechaza_v1_ausencias_y_procedencia(self):
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            inv.DB_PATH.replace(self.op / 'anterior-base')
            self.assertEqual(coord.seleccionar_originales()['estado'], 'evidencia insuficiente')
            self.datos.update(estado='pendiente', paso='base-guardar')
            r.escribir(self.datos)
            self.assertEqual(coord.seleccionar_originales()['estado'], 'candidato identificado')
            (self.op / 'anterior-base').write_bytes(b'alterada')
            self.assertNotEqual(coord.seleccionar_originales()['estado'], 'candidato identificado')
            legado = {k: v for k, v in self.datos.items() if k in r.BASE}; legado['version'] = 1
            r.REGISTRO.write_text(json.dumps(legado))
            self.assertEqual(coord.seleccionar_originales()['estado'], 'evidencia insuficiente')

    def test_seleccion_hash_y_archivo_faltante(self):
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(sel, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            documento = inv.STORAGE_DIR / 'documento.txt'
            original = documento.read_bytes(); info = documento.stat()
            documento.write_bytes(b'x' * len(original))
            os.utime(documento, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.assertEqual(coord.seleccionar_originales()['estado'], 'candidato rechazado')
            documento.unlink()
            self.assertNotEqual(coord.seleccionar_originales()['estado'], 'candidato identificado')

    def test_diagnostico_pendiente_sin_modificar_datos(self):
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(diag, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            antes = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            informe = coord.diagnosticar_restauracion()
            self.assertEqual(informe['clasificacion'], 'evidencia coherente')
            self.assertEqual(informe['operaciones'][0]['archivos_anteriores']['disponibles'], 2)
            with self.assertRaises(RuntimeError):
                coord.BloqueoDatos(False)
            despues = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.name != '.siged-coordinacion.lock'}
            self.assertEqual(antes, despues)
            inv.DB_PATH.write_bytes(b'alterada')
            informe = coord.diagnosticar_restauracion()
            self.assertEqual(informe['clasificacion'], 'información insuficiente o estado incierto')
            inv.DB_PATH.unlink()
            self.assertEqual(coord.diagnosticar_restauracion()['operaciones'][0]['archivos_anteriores']['ausentes'], 1)
            with patch.object(diag, '_inspeccionar', side_effect=RuntimeError('error')):
                with self.assertRaises(RuntimeError): coord.diagnosticar_restauracion()
            self.assertTrue(coord.diagnosticar_restauracion())

    def test_diagnostico_incierto_y_discrepancia(self):
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(diag, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            self.assertEqual(coord.diagnosticar_restauracion()['clasificacion'], 'información insuficiente o estado incierto')
            r.REGISTRO.write_text('{')
            self.assertEqual(coord.diagnosticar_restauracion()['clasificacion'], 'información insuficiente o estado incierto')
            legado = {k: v for k, v in self.datos.items() if k in r.BASE}
            legado['version'] = 1
            r.REGISTRO.write_text(json.dumps(legado))
            self.assertEqual(coord.diagnosticar_restauracion()['clasificacion'], 'información insuficiente o estado incierto')
            r.REGISTRO.unlink()
            r.escribir(self.datos)
            inv.DB_PATH.replace(self.op / 'anterior-base')
            (self.op / 'anterior-base').write_bytes(b'alterado')
            self.assertEqual(coord.diagnosticar_restauracion()['clasificacion'], 'discrepancia comprobada')

    def test_diagnostico_conjuntos_modos_y_limites(self):
        r.escribir(self.datos)
        with patch.object(coord, 'DATA_DIR', self.root), patch.multiple(diag, DB_PATH=inv.DB_PATH, STORAGE_DIR=inv.STORAGE_DIR, SECRET_PATH=inv.SECRET_PATH):
            rapido = coord.diagnosticar_restauracion('rapido')
            self.assertEqual(rapido['clasificacion'], 'información insuficiente o estado incierto')
            self.assertTrue(any(d['categoria'] == 'sin verificar' for d in rapido['operaciones'][0]['detalles']))
            with patch.object(inv, 'huella', side_effect=KeyboardInterrupt):
                cancelado = coord.diagnosticar_restauracion()
                self.assertEqual(cancelado['clasificacion'], 'información insuficiente o estado incierto')
                self.assertIn('sin verificar', cancelado['motivo'])
            preparado = self.op / 'validado' / 'storage' / 'documento.txt'
            preparado.unlink()
            informe = coord.diagnosticar_restauracion()
            self.assertTrue(any(d['conjunto'] == 'preparado' and d['categoria'] == 'archivo ausente' for d in informe['operaciones'][0]['detalles']))
            contenido = self.previo.read_bytes()
            self.previo.write_bytes(b'x' * len(contenido))
            informe = coord.diagnosticar_restauracion()
            self.assertEqual(informe['clasificacion'], 'discrepancia comprobada')
            self.assertTrue(any(d['conjunto'] == 'respaldo' and d['categoria'] == 'hash diferente' for d in informe['operaciones'][0]['detalles']))
            with patch.dict(os.environ, {'GESTOR_DIAGNOSTICO_MAX_BYTES': '1'}):
                limitado = coord.diagnosticar_restauracion()
                self.assertEqual(limitado['clasificacion'], 'información insuficiente o estado incierto')
                self.assertIn('sin verificar', limitado['motivo'])

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
