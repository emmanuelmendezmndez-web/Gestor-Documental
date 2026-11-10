"""Restauraciones reales únicamente sobre el directorio ficticio del fixture."""

import json
import os
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing, contextmanager
from unittest.mock import patch
from zipfile import ZipFile

from aislamiento import exigir_directorio_temporal

RAIZ = exigir_directorio_temporal("siged-prueba-mensajeria-")

from app import coordinacion as coord
from app import registro_restauracion as registro
from app import respaldo
from app.configuracion import DB_PATH, SECRET_PATH, STORAGE_DIR
from app.database import conectar, inicializar_db
from app.mensajeria import base_datos as bd
from app.mensajeria import reconciliacion as rec
from app.mensajeria.identidad import IdentidadNoVerificada


def usuario(db, numero, nombre):
    db.execute(
        "INSERT INTO usuarios(id, usuario, nombre, password_hash, rol) VALUES (?, ?, ?, 'ficticio', 'lector')",
        (numero, nombre, nombre),
    )


def documento(db, numero, nombre):
    (STORAGE_DIR / nombre).write_bytes(b"ficticio")
    db.execute(
        "INSERT INTO documentos(id,titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes) "
        "VALUES (?, 'titulo-ficticio', ?, ?, 'Oficios', 8)",
        (numero, nombre, nombre),
    )


class ReconciliacionCasos(unittest.TestCase):
    def _confirmar(self, estado):
        informe = rec.diagnosticar()
        self.assertEqual(informe["estado"], estado, informe)
        self.assertEqual(rec.reconciliar(informe["confirmacion"]), {"estado": "identidad_coherente"})
        self.assertEqual(rec.reconciliar(informe["confirmacion"]), {"estado": "identidad_coherente"})
        return informe["confirmacion"]

    def _referenciar(self, usuario_a, usuario_b, doc_ref):
        with bd._conectar_infraestructura() as db:
            a, b = sorted((usuario_a, usuario_b))
            db.execute("INSERT INTO conversaciones VALUES ('c', ?, ?)", (a, b))
            db.execute(
                "INSERT INTO mensajes VALUES ('m', 'c', ?, ?, 'texto-privado-ficticio', "
                "100, 200, 'documento', ?, NULL, NULL, NULL)", (a, b, doc_ref),
            )

    def test_ciclo_de_respaldo_restauracion_y_reconciliacion(self):
        inicializar_db()
        STORAGE_DIR.mkdir()
        SECRET_PATH.write_text("clave-ficticia-exclusiva-prueba-mensajeria", encoding="utf-8")
        with patch.dict(os.environ, {"GESTOR_SECRET_KEY": ""}):
            self._ejecutar_ciclo()

    def _ejecutar_ciclo(self):
        with conectar() as db:
            usuario(db, 1, "persona-a-ficticia")
            usuario(db, 2, "persona-b-ficticia")
            documento(db, 1, "original-ficticio.txt")
        legado = respaldo.crear_respaldo(RAIZ / "legado.zip")
        privada = bd.inicializar()
        self.assertEqual(rec.diagnosticar(), {"estado": "generacion_desconocida"})
        self.assertEqual(rec.preparar_identidades()["estado"], "vinculo_pendiente")
        self._probar_corte_de_reconciliacion()
        confirmacion = self._confirmar("vinculo_pendiente")
        with conectar() as db:
            a, b = (fila[0] for fila in db.execute("SELECT mensajeria_ref FROM usuarios ORDER BY id"))
            doc_ref = db.execute("SELECT mensajeria_ref FROM documentos").fetchone()[0]
        self._referenciar(a, b, doc_ref)
        (privada.parent / "temporales" / "adjunto-ficticio").write_bytes(b"privado ficticio")
        with closing(sqlite3.connect(privada)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("UPDATE mensajes SET texto='texto-privado-ficticio'")
            db.commit()
            for sufijo in ("-wal", "-shm"):
                self.assertTrue(privada.with_name(privada.name + sufijo).exists())
            moderno = respaldo.crear_respaldo(RAIZ / "moderno.zip")
            with ZipFile(moderno) as zip_:
                self.assertEqual(set(zip_.namelist()), {
                    "database/gestor.db", "storage/", "storage/original-ficticio.txt",
                    "secrets/session_key", "manifest.json",
                })
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        with closing(sqlite3.connect(privada)) as db:
            db.execute("PRAGMA journal_mode=DELETE")
        self.assertEqual(rec.diagnosticar()["estado"], "identidad_coherente")
        inicio = subprocess.run(
            [sys.executable, "-c", """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as cliente:
    assert cliente.get('/login').status_code == 200
    assert cliente.get('/mensajeria').status_code == 404
"""],
            check=False, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(inicio.returncode, 0, inicio.stderr)
        with conectar() as db:
            db.execute("UPDATE documentos SET nombre_guardado='distinto.txt' WHERE id=1")
        self.assertEqual(rec.diagnosticar()["incidencias"]["identidades_contradictorias"], 1)
        with conectar() as db:
            db.execute("UPDATE documentos SET nombre_guardado='original-ficticio.txt' WHERE id=1")
        with coord.BloqueoDatos(exclusivo=True):
            consulta = subprocess.run(
                [sys.executable, "-m", "app.mensajeria.reconciliacion", "diagnosticar"],
                check=False, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(json.loads(consulta.stdout), {"estado": "bloqueo_no_disponible"})
        with conectar() as db:
            db.execute("UPDATE usuarios SET activo=0 WHERE id=2")
        self.assertEqual(rec.diagnosticar()["incidencias"]["usuarios_inactivos"], 1)
        with conectar() as db:
            db.execute("DELETE FROM usuarios WHERE id=2")
            db.execute("DELETE FROM documentos WHERE id=1")
            usuario(db, 2, "persona-b-ficticia")
            documento(db, 1, "reemplazo-ficticio.txt")
            self.assertNotEqual(db.execute("SELECT mensajeria_ref FROM usuarios WHERE id=2").fetchone()[0], b)
            self.assertNotEqual(db.execute("SELECT mensajeria_ref FROM documentos").fetchone()[0], doc_ref)
        informe = rec.diagnosticar()
        self.assertEqual(informe["incidencias"]["usuarios_inexistentes"], 1)
        self.assertEqual(informe["incidencias"]["documentos_inexistentes"], 1)
        self.assertNotIn("ficticio", json.dumps(informe))
        respaldo.restaurar_respaldo(moderno)
        self.assertEqual(rec.reconciliar(confirmacion), {"estado": "confirmacion_invalida"})
        confirmacion = self._confirmar("generacion_incompatible")
        self._interrumpir_y_recuperar(moderno)
        self.assertEqual(rec.reconciliar(confirmacion), {"estado": "confirmacion_invalida"})
        self._confirmar("generacion_incompatible")
        with conectar() as db:
            usuario(db, 3, "persona-posterior-ficticia")
            posterior = db.execute("SELECT mensajeria_ref FROM usuarios WHERE id=3").fetchone()[0]
        with bd._conectar_infraestructura() as db:
            db.execute("INSERT INTO conversaciones VALUES ('posterior', ?, ?)", sorted((a, posterior)))
        respaldo.restaurar_respaldo(moderno)
        informe = rec.diagnosticar()
        self.assertEqual(informe["incidencias"]["usuarios_inexistentes"], 1)
        self.assertTrue(informe["generacion_cambio"])
        self.assertNotIn("confirmacion", informe)
        respaldo.restaurar_respaldo(legado)
        self.assertEqual(rec.diagnosticar(), {"estado": "generacion_desconocida"})
        self.assertEqual(rec.preparar_identidades(), {"estado": "generacion_desconocida"})
        with bd._conectar_infraestructura() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM mensajes").fetchone()[0], 1)
        with self.assertRaises(IdentidadNoVerificada), bd.conectar():
            self.fail("La reconciliación no habilita acceso funcional")

    def _probar_corte_de_reconciliacion(self):
        confirmacion = rec.diagnosticar()["confirmacion"]
        bases = rec._bases

        @contextmanager
        def corte():
            with bases() as conexiones:
                yield conexiones
                raise OSError("corte ficticio antes de cerrar la transacción")

        with patch.object(rec, "_bases", corte):
            self.assertEqual(rec.reconciliar(confirmacion), {"estado": "almacenamiento_no_disponible"})
        self.assertEqual(rec.diagnosticar()["estado"], "vinculo_pendiente")

    def _interrumpir_y_recuperar(self, moderno):
        escribir = respaldo.escribir_registro

        def interrumpir(datos):
            if datos["paso"] == "base-instalar" and datos["estado"] == "confirmada":
                raise OSError("interrupción ficticia tras instalar la base")
            escribir(datos)

        with patch.object(respaldo, "escribir_registro", side_effect=interrumpir), self.assertRaises(OSError):
            respaldo.restaurar_respaldo(moderno)
        self.assertEqual(rec.diagnosticar(), {"estado": "recuperacion_incompleta_o_incierta"})
        op = registro.leer(registro.REGISTRO)["operacion"]
        preparacion = coord.preparar_persistente()
        self.assertEqual(preparacion["estado"], "preparación íntegra", preparacion)
        aplicacion = coord.aplicar_recuperacion(op, op)
        self.assertEqual(aplicacion["estado"], "instalación verificada; arranque bloqueado", aplicacion)
        self.assertEqual(rec.diagnosticar(), {"estado": "recuperacion_incompleta_o_incierta"})
        cierre = coord.finalizar_recuperacion(op, op)
        self.assertTrue(cierre["listo_recuperacion"], cierre)
        self.assertTrue(DB_PATH.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
