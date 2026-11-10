"""Casos internos: solo pueden ejecutarse en el directorio temporal del fixture."""

import hashlib
import os
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from aislamiento import exigir_directorio_temporal

RAIZ_TEMPORAL = exigir_directorio_temporal("siged-prueba-mensajeria-")

from app.mensajeria import base_datos as bd
from app.mensajeria.configuracion import directorio_configurado
from app.mensajeria.identidad import IdentidadNoVerificada, exigir_identidad_verificada


class MensajeriaInfraestructuraCasos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = bd.inicializar()

    def test_creacion_acl_y_esquema(self):
        self.assertTrue(self.base.is_file())
        self.assertTrue((self.base.parent / "temporales").is_dir())
        self.assertTrue((self.base.parent / "confirmados").is_dir())
        with bd._conectar_infraestructura() as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], bd.APPLICATION_ID)
            self.assertEqual(db.execute("SELECT estado FROM contexto").fetchone()[0], "no_verificada")

    def test_inicializacion_repetida_preserva_datos(self):
        with bd._conectar_infraestructura() as db:
            db.execute("INSERT OR IGNORE INTO conversaciones VALUES (?, ?, ?)",
                       ("persistente", "a" * 32, "b" * 32))
        self.assertEqual(bd.inicializar(), self.base)
        with bd._conectar_infraestructura() as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM conversaciones WHERE id='persistente'"
            ).fetchone()[0], 1)

    def test_migracion_interrumpida_es_atomica_y_repetible(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA foreign_keys=ON")
            with patch.object(bd, "ESTRUCTURA", (*bd.ESTRUCTURA[:3], "SQL INVALIDO")), self.assertRaises(sqlite3.OperationalError):
                bd._migrar(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0], 0)
            bd._migrar(db)
            bd._migrar(db)

    def test_corte_abrupto_durante_migracion(self):
        archivo = RAIZ_TEMPORAL / "corte-ficticio.sqlite3"
        codigo = """
import os, sqlite3, sys
from app.mensajeria.base_datos import _migrar
db = sqlite3.connect(sys.argv[1])
class Corte:
    def execute(self, sql, *args):
        if sql.startswith("CREATE TABLE mensajes"):
            os._exit(17)
        return db.execute(sql, *args)
    def commit(self): return db.commit()
    def rollback(self): return db.rollback()
_migrar(Corte())
"""
        try:
            resultado = subprocess.run(
                [sys.executable, "-c", codigo, str(archivo)], check=False, timeout=30
            )
            self.assertEqual(resultado.returncode, 17)
            with closing(sqlite3.connect(archivo)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0], 0)
                db.execute("PRAGMA foreign_keys=ON")
                bd._migrar(db)
        finally:
            archivo.unlink(missing_ok=True)

    def test_esquema_ajeno_y_version_desconocida(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE ajena(id INTEGER)")
            with self.assertRaises(ValueError):
                bd._migrar(db)
            self.assertIsNotNone(db.execute(
                "SELECT name FROM sqlite_master WHERE name='ajena'"
            ).fetchone())
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA user_version = 99")
            with self.assertRaises(ValueError):
                bd._migrar(db)

    def test_migracion_aditiva_desde_fase_uno(self):
        with closing(sqlite3.connect(":memory:")) as db:
            for sql in bd.ESTRUCTURA:
                db.execute(sql)
            db.execute(f"PRAGMA application_id = {bd.APPLICATION_ID}")
            db.execute("PRAGMA user_version = 1")
            db.execute("INSERT INTO conversaciones VALUES (?, ?, ?)", ("legado", "a" * 32, "b" * 32))
            db.commit()
            bd._migrar(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT id FROM conversaciones").fetchone()[0], "legado")
            self.assertIsNone(db.execute("SELECT id FROM vinculo_identidad").fetchone())

    def test_migracion_v2_conserva_operacion_confirmada(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("PRAGMA foreign_keys=ON")
            for sql in (*bd.ESTRUCTURA, *bd.ESTRUCTURA_V2):
                db.execute(sql)
            db.execute(f"PRAGMA application_id = {bd.APPLICATION_ID}")
            db.execute("PRAGMA user_version = 2")
            a, b = "a" * 32, "b" * 32
            db.execute("INSERT INTO conversaciones VALUES ('c', ?, ?)", (a, b))
            db.execute(
                "INSERT INTO mensajes VALUES ('m', 'c', ?, ?, 'ficticio', 100, 200, "
                "'documento', ?, NULL, NULL, NULL)", (a, b, "d" * 32),
            )
            db.execute("INSERT INTO operaciones VALUES (?, 'legada', 'confirmada', 'm')", (a,))
            db.commit()
            bd._migrar(db)
            self.assertEqual(db.execute("SELECT mensaje_id, resultado_id, huella FROM operaciones").fetchone(),
                             ("m", "m", None))
            db.execute("DELETE FROM mensajes WHERE id='m'")
            self.assertEqual(db.execute("SELECT mensaje_id, resultado_id FROM operaciones").fetchone(), (None, "m"))
            self.assertIsNone(db.execute("PRAGMA foreign_key_check").fetchone())

    def test_falta_de_indice_o_disparador_rechaza_esquema(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA foreign_keys=ON")
            bd._migrar(db)
            db.execute("DROP TRIGGER mensajes_participantes_insert")
            db.commit()
            with self.assertRaises(ValueError):
                bd._migrar(db)

    def test_relaciones_y_adjunto_obligatorio(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA foreign_keys=ON")
            bd._migrar(db)
            a, b, x = "a" * 32, "b" * 32, "c" * 32
            db.execute("INSERT INTO conversaciones VALUES (?, ?, ?)", ("c", a, b))
            sql = "INSERT INTO mensajes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            externo = ("m", "c", a, b, "ok", 100, 10900, "externo",
                       None, "a" * 32, "documento.pdf", 100)
            db.execute(sql, externo)
            variantes = [
                ("otro", "c", a, x, "", 100, 10900, "externo", None, "b" * 32, "x", 1),
                ("otro", "c", a, b, "x" * 301, 100, 10900, "externo", None, "b" * 32, "x", 1),
                ("otro", "c", a, b, "", 100, 10900, "externo", None, "b" * 32, "x", None),
                ("otro", "c", a, b, "", 100, 10900, "externo", "doc", "b" * 32, "x", 1),
                ("otro", "c", a, b, "", 100, 10900, "externo", None, "../archivo", "x", 1),
                ("otro", "c", a, b, "", 100, 10901, "externo", None, "b" * 32, "x", 1),
                ("otro", "c", a, b, "", 100, 10900, "externo", None, "b" * 32, "x", 20971521),
                ("otro", "c", a, b, "", 100, 604901, "documento", "d" * 32, None, None, None),
            ]
            for datos in variantes:
                with self.subTest(datos=datos), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql, datos)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO estado_participante VALUES (?, ?, 0, NULL)", ("c", x))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO cuotas VALUES ('a', '2026-01-01', 51)")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO operaciones(usuario_ref, clave, estado) VALUES ('a', 'clave', 'confirmada')")

    def test_identidad_no_se_puede_habilitar(self):
        with self.assertRaises(IdentidadNoVerificada):
            exigir_identidad_verificada()
        with self.assertRaises(IdentidadNoVerificada), bd.conectar():
            self.fail("No debe permitirse una conexión funcional")
        with bd._conectar_infraestructura() as db, self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE contexto SET estado='verificada' WHERE id=1")

    def test_rutas_no_autorizadas_o_inexistentes(self):
        original = os.environ["GESTOR_MENSAJERIA_DIR"]
        try:
            for ruta in ("", "relativa/.siged-mensajeria",
                         str(Path(__file__).resolve().parents[1] / ".siged-mensajeria"),
                         str(RAIZ_TEMPORAL / "storage" / ".siged-mensajeria"),
                         str(RAIZ_TEMPORAL / "respaldos" / ".siged-mensajeria"),
                         str(RAIZ_TEMPORAL / "inexistente" / ".siged-mensajeria")):
                os.environ["GESTOR_MENSAJERIA_DIR"] = ruta
                with self.subTest(ruta=ruta), self.assertRaises((OSError, ValueError)):
                    directorio_configurado()
        finally:
            os.environ["GESTOR_MENSAJERIA_DIR"] = original

    def test_fallo_acl_no_abre_base(self):
        with patch.object(bd, "verificar_acl_privada", side_effect=OSError("ACL")), self.assertRaises(OSError), bd._conectar_infraestructura():
            self.fail("Una ACL no verificable debe impedir el acceso")

    def test_fallo_al_crear_raiz_no_crea_base(self):
        padre = RAIZ_TEMPORAL / "padre-ficticio"
        padre.mkdir(exist_ok=True)
        raiz = padre / ".siged-mensajeria"
        with (
            patch.dict(os.environ, {"GESTOR_MENSAJERIA_DIR": str(raiz)}),
            patch.object(bd, "directorio_privado", side_effect=PermissionError),
            self.assertRaises(PermissionError),
        ):
            bd.inicializar()
        self.assertFalse(raiz.exists())

    def test_archivos_ajenos_se_conservan_y_respaldo_los_excluye(self):
        from app.database import inicializar_db
        from app.respaldo import crear_respaldo

        inicializar_db()
        storage = RAIZ_TEMPORAL / "storage"
        storage.mkdir(exist_ok=True)
        documento = storage / "ficticio.txt"
        documento.write_bytes(b"documento ficticio")
        with bd._conectar_infraestructura() as db:
            db.execute("INSERT OR IGNORE INTO conversaciones VALUES (?, ?, ?)",
                       ("no-respaldar", "c" * 32, "d" * 32))
        archivo = self.base.parent / "confirmados" / "adjunto-ficticio"
        archivo.write_bytes(b"adjunto ficticio")
        hash_principal = hashlib.sha256((RAIZ_TEMPORAL / "gestor.db").read_bytes()).hexdigest()
        respaldo = crear_respaldo()
        with ZipFile(respaldo) as z:
            self.assertFalse(any(".siged-mensajeria" in nombre for nombre in z.namelist()))
            self.assertNotIn("adjunto-ficticio", " ".join(z.namelist()))
            copia = RAIZ_TEMPORAL / "copia-ficticia.sqlite3"
            copia.write_bytes(z.read("database/gestor.db"))
        try:
            with closing(sqlite3.connect(copia)) as db:
                tablas = {fila[0] for fila in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
            self.assertNotIn("mensajes", tablas)
            self.assertNotIn("conversaciones", tablas)
        finally:
            copia.unlink(missing_ok=True)
        self.assertEqual(hash_principal, hashlib.sha256(
            (RAIZ_TEMPORAL / "gestor.db").read_bytes()
        ).hexdigest())
        self.assertEqual(documento.read_bytes(), b"documento ficticio")
        self.assertEqual(archivo.read_bytes(), b"adjunto ficticio")


if __name__ == "__main__":
    unittest.main(verbosity=2)
