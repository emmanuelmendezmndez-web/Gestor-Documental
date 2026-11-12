import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from app.servicios import estado_sistema as servicio


class EstadoSistemaTest(unittest.TestCase):
    def setUp(self):
        carpeta = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.base = carpeta / "gestor.db"
        self.archivos = carpeta / "storage"
        self.archivos.mkdir()
        with closing(sqlite3.connect(self.base)) as db, db:
            db.executescript("""
                CREATE TABLE usuarios (id INTEGER PRIMARY KEY, rol TEXT, version_sesion INTEGER, activo INTEGER);
                INSERT INTO usuarios VALUES (1, 'lector', 2, 1), (2, 'sin_permiso', 2, 1);
                CREATE TABLE documentos (id INTEGER PRIMARY KEY);
                CREATE TABLE expedientes (id INTEGER PRIMARY KEY);
            """)
        self.enterContext(patch.multiple(servicio, DB_PATH=self.base, STORAGE_DIR=self.archivos, _cache={}))
        self.sesion = {"usuario_id": 1, "version": 2}
        self.disco = self.enterContext(patch.object(servicio.shutil, "disk_usage"))
        self.disco.return_value = Mock(total=100, free=40)

    def test_operativo_y_cache_compartida_por_un_minuto(self):
        with patch.object(servicio, "monotonic", return_value=100) as reloj:
            self.assertEqual(servicio.consultar_estado_sistema(self.sesion, False), (
                200, {"estado": "operativo", "incidencias": []},
            ))
            self.disco.return_value.free = 10
            self.assertEqual(servicio.consultar_estado_sistema(self.sesion, False)[1]["estado"], "operativo")
            self.assertEqual(self.disco.call_count, 1)
            reloj.return_value = 160
            self.assertEqual(servicio.consultar_estado_sistema(self.sesion, False)[1]["estado"], "degradado")

    def test_storage_sin_espacio_o_inaccesible_es_critico(self):
        self.disco.return_value.free = 0
        self.assertEqual(servicio.consultar_estado_sistema(self.sesion, False)[1]["estado"], "critico")
        servicio._cache.clear()
        self.archivos.rmdir()
        resultado = servicio.consultar_estado_sistema(self.sesion, False)[1]
        self.assertEqual(resultado["estado"], "critico")
        self.assertNotIn(str(self.archivos), str(resultado))

    def test_base_ausente_es_critica_y_no_se_crea(self):
        self.base.unlink()
        codigo, resultado = servicio.consultar_estado_sistema(self.sesion, False)
        self.assertEqual((codigo, resultado["estado"]), (200, "critico"))
        self.assertFalse(self.base.exists())

    def test_mensajeria_solo_se_sondea_si_esta_habilitada(self):
        with patch.object(servicio, "_comprobar_mensajeria", side_effect=OSError("ruta privada")) as sonda:
            self.assertEqual(servicio.consultar_estado_sistema(self.sesion, False)[1]["estado"], "operativo")
            sonda.assert_not_called()
            resultado = servicio.consultar_estado_sistema(self.sesion, True)[1]
            sonda.assert_called_once()
            self.assertEqual(resultado["estado"], "degradado")
            self.assertIn("Mensajería", resultado["incidencias"][0])
            self.assertNotIn("ruta privada", str(resultado))

    def test_mensajeria_lee_base_privada_y_detecta_vinculo_ajeno(self):
        from app.mensajeria.base_datos import APPLICATION_ID, NOMBRE_BASE, VERSION

        privada = self.base.with_name(NOMBRE_BASE)
        with closing(sqlite3.connect(privada)) as db, db:
            db.executescript(f"""
                PRAGMA application_id = {APPLICATION_ID};
                PRAGMA user_version = {VERSION};
                CREATE TABLE conversaciones (id TEXT);
                CREATE TABLE mensajes (id TEXT);
                CREATE TABLE vinculo_identidad (id INTEGER PRIMARY KEY, instalacion_id TEXT, generacion_id TEXT);
                INSERT INTO vinculo_identidad VALUES (1, 'instalacion-a', 'generacion-a');
            """)
        with (
            patch("app.mensajeria.configuracion.directorio_configurado", return_value=privada.parent),
            patch("app.temporal_privado.verificar_acl_base_privada"),
            patch("app.mensajeria.identidad_documental.instalacion", return_value="instalacion-a") as identidad,
        ):
            self.assertEqual(servicio.consultar_estado_sistema(self.sesion, True)[1]["estado"], "operativo")
            identidad.return_value = "instalacion-b"
            servicio._cache.clear()
            resultado = servicio.consultar_estado_sistema(self.sesion, True)[1]
            self.assertEqual(resultado["estado"], "degradado")
            self.assertIn("vínculo", resultado["incidencias"][0])

    def test_exige_sesion_vigente_y_permiso(self):
        self.assertEqual(servicio.consultar_estado_sistema({}, False)[0], 401)
        self.assertEqual(servicio.consultar_estado_sistema({"usuario_id": 1, "version": 1}, False)[0], 401)
        self.assertEqual(servicio.consultar_estado_sistema({"usuario_id": 2, "version": 2}, False)[0], 403)
        self.disco.assert_not_called()
