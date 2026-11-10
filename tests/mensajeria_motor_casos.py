"""Casos del motor con dos bases ficticias y el bloqueo real de SIGED."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from aislamiento import exigir_directorio_temporal

RAIZ = exigir_directorio_temporal("siged-prueba-mensajeria-")

from app import respaldo
from app.configuracion import STORAGE_DIR
from app.database import conectar, inicializar_db
from app.mensajeria import base_datos as bd
from app.mensajeria import motor
from app.mensajeria import reconciliacion as rec


def verificar(solicitud):
    return isinstance(solicitud, motor.VerificacionAdjunto)


class MotorCasos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_db()
        STORAGE_DIR.mkdir()
        with conectar() as db:
            for nombre in ("uno", "dos", "tres"):
                db.execute(
                    "INSERT INTO usuarios(usuario, nombre, password_hash, rol) VALUES (?, ?, 'ficticio', 'lector')",
                    (nombre, nombre),
                )
        cls.base = bd.inicializar()
        informe = rec.preparar_identidades()
        if rec.reconciliar(informe["confirmacion"])["estado"] != "identidad_coherente":
            raise AssertionError("Fixture de identidad no reconciliado")
        with conectar() as db:
            cls.a, cls.b, cls.c = (fila[0] for fila in db.execute("SELECT mensajeria_ref FROM usuarios ORDER BY id"))

    def setUp(self):
        with bd._conectar_infraestructura() as db:
            for tabla in ("eventos", "operaciones", "mensajes", "estado_participante",
                          "conversaciones", "cuotas", "limpieza", "reloj_motor"):
                db.execute(f"DELETE FROM {tabla}")
        self.instante = int(datetime(2026, 1, 2, 5, 59, 59, tzinfo=UTC).timestamp())
        self.enterContext(patch.dict(os.environ, {"GESTOR_MENSAJERIA_ZONA_HORARIA": "-06:00"}))
        self.enterContext(patch.object(motor, "_ahora", side_effect=lambda: self.instante))

    def _archivo(self):
        return motor.Adjunto("externo", uuid4().hex, "ficticio.txt", 8)

    def _enviar(self, texto="Mensaje ficticio", clave=None, adjunto=None, verificador=verificar):
        return motor._enviar_con_adaptador(self.a, self.b, texto, clave or uuid4().hex,
                                          adjunto or self._archivo(), verificador)

    def _conteos(self):
        with bd._conectar_infraestructura() as db:
            return tuple(db.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
                         for tabla in ("mensajes", "operaciones", "eventos", "cuotas", "conversaciones"))

    def test_conversaciones_concurrentes_y_participantes(self):
        self.assertIsNone(motor.conversacion(self.a, self.b))
        with ThreadPoolExecutor(2) as pool:
            uno = pool.submit(motor.conversacion, self.a, self.b, crear=True)
            dos = pool.submit(motor.conversacion, self.b, self.a, crear=True)
            conversacion_id = uno.result(timeout=60)
            self.assertEqual(conversacion_id, dos.result(timeout=60))
        self.assertEqual(motor.conversacion(self.b, self.a), conversacion_id)
        self.assertEqual(self._conteos(), (0, 0, 0, 0, 1))
        with self.assertRaisesRegex(motor.ErrorMotor, "autoenvio_no_permitido"):
            motor.conversacion(self.a, self.a, crear=True)
        with self.assertRaisesRegex(motor.ErrorMotor, "usuario_no_disponible"):
            motor.conversacion(self.a, uuid4().hex, crear=True)
        with conectar() as db:
            db.execute("UPDATE usuarios SET activo=0 WHERE mensajeria_ref=?", (self.c,))
        try:
            with self.assertRaisesRegex(motor.ErrorMotor, "usuario_no_disponible"):
                motor.conversacion(self.a, self.c, crear=True)
        finally:
            with conectar() as db:
                db.execute("UPDATE usuarios SET activo=1 WHERE mensajeria_ref=?", (self.c,))
        with self.assertRaisesRegex(motor.ErrorMotor, "conversacion_no_disponible"):
            motor.mensajes(self.c, conversacion_id)

    def test_unicode_adjunto_y_evento_minimo(self):
        for texto in ("", "  ", "🦋" * 301, "\x00", "\ud800"):
            with self.subTest(longitud=len(texto)), self.assertRaisesRegex(motor.ErrorMotor, "texto_invalido"):
                self._enviar(texto)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_obligatorio"):
            motor.enviar(self.a, self.b, "Ficticio", uuid4().hex, None)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_invalido"):
            self._enviar(adjunto=motor.Adjunto("externo", uuid4().hex, "ficticio.txt", 20971521))
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_no_confirmado"):
            self._enviar(verificador=None)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_no_confirmado"):
            self._enviar(verificador=lambda _: False)
        self.assertEqual(self._conteos(), (0, 0, 0, 0, 0))
        texto = "🦋" * 299 + "á"
        mensaje_id = self._enviar(texto)
        with bd._conectar_infraestructura() as db:
            mensaje = db.execute("SELECT texto, length(texto), vence_utc-confirmado_utc FROM mensajes").fetchone()
            self.assertEqual(tuple(mensaje), (texto, 300, 10800))
            evento = db.execute("SELECT * FROM eventos").fetchone()
            self.assertEqual(tuple(evento)[1:], (mensaje_id, self.b, "mensaje_confirmado", self.instante, 0))
        self.assertEqual(motor.cuota(self.a)["envios"], 1)
        self.assertEqual(motor.cuota(self.b)["envios"], 0)

    def test_cuota_limites_respuesta_y_dia_institucional(self):
        self._enviar()
        self.assertEqual(motor.cuota(self.a), {"dia": "2026-01-01", "envios": 1, "limite": 50})
        with bd._conectar_infraestructura() as db:
            db.execute("UPDATE cuotas SET envios=48")
        self._enviar()
        self.assertEqual(motor.cuota(self.a)["envios"], 49)
        self._enviar()
        with self.assertRaisesRegex(motor.ErrorMotor, "cuota_agotada"):
            self._enviar()
        self.assertEqual(motor.cuota(self.a)["envios"], 50)
        motor._enviar_con_adaptador(self.b, self.a, "Respuesta ficticia", uuid4().hex, self._archivo(), verificar)
        self.assertEqual(motor.cuota(self.b)["envios"], 1)
        self.instante += 1
        self.assertEqual(motor.cuota(self.a), {"dia": "2026-01-02", "envios": 0, "limite": 50})
        self._enviar()
        self.assertEqual(motor.cuota(self.a)["envios"], 1)
        self.instante -= 1
        with self.assertRaisesRegex(motor.ErrorMotor, "reloj_retrocedio"):
            self._enviar()
        self.instante += 1
        with patch.dict(os.environ, {"GESTOR_MENSAJERIA_ZONA_HORARIA": "UTC"}), self.assertRaisesRegex(
            motor.ErrorMotor, "zona_horaria_incompatible"
        ):
            self._enviar()

    def test_carrera_con_una_cuota(self):
        with bd._conectar_infraestructura() as db:
            db.execute("INSERT INTO cuotas VALUES (?, '2026-01-01', 49)", (self.a,))
        barrera = Barrier(2, timeout=60)

        def enviar():
            try:
                return self._enviar(verificador=lambda _: barrera.wait() >= 0)
            except motor.ErrorMotor as error:
                return str(error)

        with ThreadPoolExecutor(2) as pool:
            resultados = tuple(pool.map(lambda _: enviar(), range(2)))
        self.assertEqual(resultados.count("cuota_agotada"), 1)
        self.assertEqual(motor.cuota(self.a)["envios"], 50)
        self.assertEqual(self._conteos(), (1, 1, 1, 1, 1))

    def test_idempotencia_concurrente_y_conflicto(self):
        clave, adjunto = uuid4().hex, self._archivo()
        barrera = Barrier(2, timeout=60)
        with ThreadPoolExecutor(2) as pool:
            ids = tuple(pool.map(lambda _: self._enviar(
                clave=clave, adjunto=adjunto, verificador=lambda _: barrera.wait() >= 0,
            ), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self._enviar(clave=clave, adjunto=adjunto, verificador=None), ids[0])
        with self.assertRaisesRegex(motor.ErrorMotor, "conflicto_idempotencia"):
            self._enviar(texto="Otro texto", clave=clave, adjunto=adjunto)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_ya_utilizado"):
            self._enviar(adjunto=adjunto)
        self.assertEqual(self._conteos(), (1, 1, 1, 1, 1))
        self.assertEqual(motor.cuota(self.a)["envios"], 1)

    def test_descriptor_documental_sin_acceso_a_biblioteca(self):
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_no_disponible"):
            self._enviar(adjunto=motor.Adjunto("documento", uuid4().hex))
        self.assertEqual(self._conteos(), (0, 0, 0, 0, 0))
        ruta = STORAGE_DIR / "referencia-ficticia.txt"
        ruta.write_bytes(b"ficticio")
        with conectar() as db:
            db.execute(
                "INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes) "
                "VALUES ('ficticio', 'referencia-ficticia.txt', 'referencia-ficticia.txt', 'Oficios', 8)"
            )
            referencia = db.execute("SELECT mensajeria_ref FROM documentos").fetchone()[0]
        self._enviar(adjunto=motor.Adjunto("documento", referencia))
        fila = motor.mensajes(self.b, motor.conversacion(self.a, self.b))[0]
        self.assertEqual(fila["tipo_adjunto"], "documento")
        self.assertEqual(fila["vence_utc"] - fila["confirmado_utc"], 7 * 86400)
        self.assertNotIn("documento_ref", fila)
        self.assertNotIn("nombre_original", fila)

    def test_fallo_antes_y_perdida_despues_del_commit(self):
        persistir = motor._persistir

        def antes(*args):
            persistir(*args)
            raise OSError("corte ficticio antes del commit")

        with patch.object(motor, "_persistir", side_effect=antes), self.assertRaises(OSError):
            self._enviar()
        self.assertEqual(self._conteos(), (0, 0, 0, 0, 0))
        bases = motor._bases
        intentos = 0

        @contextmanager
        def despues():
            nonlocal intentos
            with bases() as datos:
                yield datos
            intentos += 1
            if intentos == 2:
                raise TimeoutError("respuesta ficticia perdida")

        clave, adjunto = uuid4().hex, self._archivo()
        with patch.object(motor, "_bases", despues), self.assertRaises(TimeoutError):
            self._enviar(clave=clave, adjunto=adjunto)
        with bd._conectar_infraestructura() as db:
            esperado = db.execute("SELECT id FROM mensajes").fetchone()[0]
        self.assertEqual(self._enviar(clave=clave, adjunto=adjunto, verificador=None), esperado)
        self.assertEqual(self._conteos(), (1, 1, 1, 1, 1))

    def test_lectura_archivado_retencion_y_limpieza(self):
        clave, adjunto = uuid4().hex, self._archivo()
        mensaje_id = self._enviar(clave=clave, adjunto=adjunto)
        conversacion_id = motor.conversacion(self.a, self.b)
        self.assertIsNone(motor.mensajes(self.b, conversacion_id)[0]["leido_utc"])
        with self.assertRaisesRegex(motor.ErrorMotor, "mensaje_no_disponible"):
            motor.marcar_leido(self.a, mensaje_id)
        motor.marcar_leido(self.b, mensaje_id)
        self.assertEqual(motor.mensajes(self.b, conversacion_id)[0]["leido_utc"], self.instante)
        self.assertIsNone(motor.mensajes(self.a, conversacion_id)[0]["leido_utc"])
        motor.archivar(self.b, conversacion_id)
        self.assertEqual(motor.conversaciones(self.b), [])
        self.assertEqual(motor.conversaciones(self.b, archivadas=True)[0]["id"], conversacion_id)
        self.assertEqual(motor.conversaciones(self.a)[0]["id"], conversacion_id)
        self.assertEqual(motor.cuota(self.a)["envios"], 1)
        self.instante += motor.RETENCION - 1
        self.assertEqual(motor.mensajes(self.b, conversacion_id)[0]["id"], mensaje_id)
        self.assertEqual(motor.depurar_historial(), 0)
        self.instante += 1
        self.assertEqual(motor.mensajes(self.b, conversacion_id), [])
        self.assertEqual(motor.depurar_historial(), 1)
        self.assertEqual(motor.depurar_historial(), 0)
        self.assertEqual(self._conteos(), (0, 1, 0, 1, 1))
        self.assertEqual(self._enviar(clave=clave, adjunto=adjunto, verificador=None), mensaje_id)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_ya_utilizado"):
            self._enviar(adjunto=adjunto)
        with bd._conectar_infraestructura() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM lecturas").fetchone()[0], 0)
            self.assertEqual(tuple(db.execute("SELECT archivo_token, estado FROM limpieza").fetchone()),
                             (adjunto.referencia, "suspendida"))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_z_restauracion_durante_verificacion(self):
        archivo = respaldo.crear_respaldo(RAIZ / "antes-del-envio.zip")

        def restaurar(_):
            respaldo.restaurar_respaldo(archivo)
            with self.assertRaisesRegex(motor.ErrorMotor, "identidad_no_reconciliada"):
                motor.conversacion(self.a, self.b)
            informe = rec.diagnosticar()
            self.assertEqual(informe["estado"], "generacion_incompatible")
            self.assertEqual(rec.reconciliar(informe["confirmacion"])["estado"], "identidad_coherente")
            return True

        with self.assertRaisesRegex(motor.ErrorMotor, "generacion_cambio"):
            self._enviar(verificador=restaurar)
        self.assertEqual(self._conteos(), (0, 0, 0, 0, 0))
        self._enviar()


if __name__ == "__main__":
    unittest.main(verbosity=2)
