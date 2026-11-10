"""Referencias de Biblioteca sobre SQLite y originales NTFS ficticios."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from aislamiento import exigir_directorio_temporal

RAIZ = exigir_directorio_temporal("siged-prueba-mensajeria-")

from app import respaldo
from app.configuracion import STORAGE_DIR
from app.coordinacion import BloqueoDatos, BloqueoNoDisponible
from app.database import conectar, inicializar_db
from app.eliminaciones import encolar, procesar_tarea
from app.mensajeria import base_datos as bd
from app.mensajeria import biblioteca, motor
from app.mensajeria import reconciliacion as rec
from app.seguridad import PERMISOS


class BibliotecaCasos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_db()
        STORAGE_DIR.mkdir()
        cls.privada = bd.inicializar().parent
        informe = rec.preparar_identidades()
        if rec.reconciliar(informe["confirmacion"])["estado"] != "identidad_coherente":
            raise AssertionError("Fixture de identidad no reconciliado")

    def setUp(self):
        for ruta in STORAGE_DIR.glob("*.*"):
            ruta.unlink()
        with bd._conectar_infraestructura() as db:
            for tabla in ("eventos", "operaciones", "mensajes", "estado_participante",
                          "conversaciones", "cuotas", "limpieza", "reloj_motor"):
                db.execute(f"DELETE FROM {tabla}")
        with conectar() as db:
            db.execute("DELETE FROM documentos")
            db.execute("DELETE FROM usuarios")
            db.executemany(
                "INSERT INTO usuarios(id,usuario,nombre,password_hash,rol,departamento) VALUES (?,?,?,'ficticio',?,?)",
                [(1, "alfa", "Alfa", "lector", "Tesorería"), (2, "beta", "Beta", "editor", "Tesorería"),
                 (3, "gama", "Gama", "lector", "Archivos"), (4, "delta", "Delta", "admin", "Archivos")],
            )
            self.a, self.b, self.c, self.admin = (
                fila[0] for fila in db.execute("SELECT mensajeria_ref FROM usuarios ORDER BY id")
            )
        self.archivo = self._crear_documento()
        self.instante = 1780000000
        self.clave = uuid4().hex
        self.enterContext(patch.dict(os.environ, {"GESTOR_MENSAJERIA_ZONA_HORARIA": "UTC"}))
        self.enterContext(patch.object(motor, "_ahora", side_effect=lambda: self.instante))

    def _crear_documento(self, numero=1, departamento="Tesorería", *, sufijo=".txt", datos=b"Texto ficticio"):
        ruta = STORAGE_DIR / (uuid4().hex + sufijo)
        ruta.write_bytes(datos)
        with conectar() as db:
            db.execute(
                """INSERT INTO documentos(id,titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,departamento)
                   VALUES (?,'Título reservado',?,?, 'Oficios',?,?)""",
                (numero, "original reservado" + sufijo, ruta.name, len(datos), departamento),
            )
        return ruta

    def _ref(self, numero=1):
        with conectar() as db:
            return db.execute("SELECT mensajeria_ref FROM documentos WHERE id=?", (numero,)).fetchone()[0]

    def _enviar(self, *, a=None, b=None, referencia=None, modalidad="visualizar", clave=None):
        return motor.enviar(a or self.a, b or self.b, "Texto del mensaje", clave or self.clave,
                            motor.Adjunto("documento", referencia or self._ref(), modalidad=modalidad))

    def _actualizar(self, sql, parametros=()):
        with conectar() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(sql, parametros)

    def _confirmado(self, **kw):
        mensaje = self._enviar(**kw)
        return motor.conversacion(self.a, self.b), mensaje

    def test_tarjeta_autorizada_modalidades_e_idempotencia(self):
        inicial = set(STORAGE_DIR.iterdir())
        conversacion, mensaje = self._confirmado()
        tarjeta = biblioteca.tarjeta(self.b, conversacion, mensaje)
        self.assertEqual(tarjeta, {
            "origen": "biblioteca", "estado": "disponible", "nombre_original": "original reservado.txt",
            "formato": "txt", "vence_utc": self.instante + 7 * 86400, "acciones": ["visualizar"],
        })
        with biblioteca.abrir_visualizacion(self.b, conversacion, mensaje) as (archivo, _):
            self.assertEqual(archivo.read(), b"Texto ficticio")
            self.assertIsInstance(archivo.name, int)
            with self.assertRaises(BloqueoNoDisponible), BloqueoDatos(exclusivo=True):
                self.fail("La restauración no debe adelantarse a una lectura abierta")
        with self.assertRaisesRegex(motor.ErrorMotor, "^documento_no_disponible$"), biblioteca.abrir_descarga(
            self.b, conversacion, mensaje,
        ):
            self.fail("La modalidad solo visualizar no admite descargas del canal")
        self.assertEqual(self._enviar(), mensaje)
        with self.assertRaisesRegex(motor.ErrorMotor, "conflicto_idempotencia"):
            self._enviar(modalidad="visualizar_y_descargar")
        self._crear_documento(2)
        with self.assertRaisesRegex(motor.ErrorMotor, "conflicto_idempotencia"):
            self._enviar(referencia=self._ref(2))
        self.assertEqual(motor.cuota(self.a)["envios"], 1)
        self.assertEqual(len(set(STORAGE_DIR.iterdir()) - inicial), 1)
        self.assertEqual(list((self.privada / "temporales").iterdir()), [])
        self.assertEqual(list((self.privada / "confirmados").iterdir()), [])
        with bd._conectar_infraestructura() as db:
            self.assertEqual(tuple(db.execute(
                "SELECT documento_ref, archivo_token, nombre_original, tamano_bytes, modalidad "
                "FROM mensajes JOIN referencias_biblioteca ON mensaje_id=id",
            ).fetchone()), (self._ref(), None, None, None, "visualizar"))
            self.assertEqual(tuple(db.execute(
                "SELECT mensaje_id,destinatario_ref,tipo FROM eventos",
            ).fetchone()), (mensaje, self.b, "mensaje_confirmado"))
        historial = motor.mensajes(self.b, conversacion)[0]
        self.assertEqual(historial["texto"], "Texto del mensaje")
        self.assertNotIn("documento_ref", historial)
        self.assertNotIn("nombre_original", historial)

    def test_denegacion_generica_roles_y_areas(self):
        referencia = self._ref()
        for a, b, ref in ((self.c, self.a, referencia), (self.a, self.c, referencia),
                          (self.admin, self.c, referencia), (self.a, self.b, uuid4().hex)):
            with self.subTest(a=a, b=b), self.assertRaisesRegex(motor.ErrorMotor, "^documento_no_disponible$"):
                self._enviar(a=a, b=b, referencia=ref)
        self.assertEqual(motor.cuota(self.a)["envios"], 0)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_invalido"):
            self._enviar(modalidad=None)
        self._enviar(a=self.admin, b=self.b, clave=uuid4().hex)
        self._crear_documento(2, departamento="")
        self._enviar(b=self.c, referencia=self._ref(2))
        self.assertEqual(motor.cuota(self.a)["envios"], 1)

    def test_descarga_revalida_permisos_participacion_y_edicion(self):
        conversacion, mensaje = self._confirmado(modalidad="visualizar_y_descargar")
        with biblioteca.abrir_descarga(self.b, conversacion, mensaje) as (archivo, cabeceras):
            self.assertEqual(archivo.read(), b"Texto ficticio")
            self.assertTrue(cabeceras["Content-Disposition"].startswith("attachment;"))
            self.assertEqual(cabeceras["Cache-Control"], "private, no-store")
        for actor, chat, id_ in (
            (self.c, conversacion, mensaje), (self.b, uuid4().hex, mensaje),
            (self.b, conversacion, "../privado"), (self.a, conversacion, self._ref()),
        ):
            self.assertEqual(biblioteca.tarjeta(actor, chat, id_), {"estado": "no_disponible"})
        with patch.dict(PERMISOS, {"editor": {"ver"}}):
            self.assertEqual(biblioteca.tarjeta(self.b, conversacion, mensaje)["acciones"], ["visualizar"])
            with self.assertRaisesRegex(motor.ErrorMotor, "^documento_no_disponible$"):
                self._enviar(modalidad="visualizar_y_descargar", clave=uuid4().hex)
            with self.assertRaisesRegex(motor.ErrorMotor, "^documento_no_disponible$"), biblioteca.abrir_descarga(
                self.b, conversacion, mensaje,
            ):
                self.fail("El permiso de descarga fue revocado")
        self._actualizar("UPDATE documentos SET titulo='Editado', version=version+1 WHERE id=1")
        self.assertEqual(biblioteca.tarjeta(self.b, conversacion, mensaje)["estado"], "disponible")
        abrir = biblioteca._abrir_original

        def cambiar_area(*args):
            resultado = abrir(*args)
            self._actualizar("UPDATE documentos SET departamento='Archivos', version=version+1 WHERE id=1")
            return resultado

        with (
            patch.object(biblioteca, "_abrir_original", side_effect=cambiar_area),
            self.assertRaisesRegex(motor.ErrorMotor, "^documento_no_disponible$"),
            biblioteca.abrir_descarga(self.b, conversacion, mensaje),
        ):
            self.fail("El área cambió antes de la autorización final")
        self.assertEqual(biblioteca.tarjeta(self.a, conversacion, mensaje), {"estado": "no_disponible"})
        self.assertEqual(motor.mensajes(self.a, conversacion)[0]["id"], mensaje)

    def test_papelera_restauracion_y_purga_preservan_historial(self):
        conversacion, mensaje = self._confirmado()
        referencia = self._ref()
        self._actualizar("UPDATE documentos SET eliminado_en='2026-01-01' WHERE id=1")
        self.assertEqual(biblioteca.tarjeta(self.a, conversacion, mensaje), {"estado": "no_disponible"})
        self._actualizar("UPDATE documentos SET eliminado_en=NULL WHERE id=1")
        self.assertEqual(biblioteca.tarjeta(self.b, conversacion, mensaje)["estado"], "disponible")
        with conectar() as db:
            tarea = encolar(db, "documento", self.archivo.name)
            db.execute("DELETE FROM documentos WHERE id=1")
        self.assertEqual(procesar_tarea(tarea), "completada")
        self.assertFalse(self.archivo.exists())
        self._crear_documento()
        self.assertNotEqual(self._ref(), referencia)
        self.assertEqual(biblioteca.tarjeta(self.b, conversacion, mensaje), {"estado": "no_disponible"})
        self.assertEqual(motor.mensajes(self.b, conversacion)[0]["id"], mensaje)

    def test_vencimiento_reenvio_y_limpieza(self):
        conversacion, mensaje = self._confirmado()
        confirmacion = self.instante
        self.instante += 7 * 86400 - 1
        self.assertEqual(biblioteca.tarjeta(self.a, conversacion, mensaje)["estado"], "disponible")
        self.instante += 1
        self.assertEqual(self._enviar(), mensaje)
        self.assertEqual(motor.cuota(self.a)["envios"], 0)
        self.assertEqual(biblioteca.tarjeta(self.b, conversacion, mensaje), {"estado": "no_disponible"})
        nuevo = self._enviar(clave=uuid4().hex)
        self.assertNotEqual(nuevo, mensaje)
        self.assertEqual(motor.cuota(self.a)["envios"], 1)
        self.instante = confirmacion + motor.RETENCION - 1
        self.assertEqual(len(motor.mensajes(self.b, conversacion)), 2)
        self.instante += 1
        self.assertEqual(motor.depurar_historial(), 1)
        self.assertTrue(self.archivo.is_file())
        with bd._conectar_infraestructura() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM limpieza").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT mensaje_id FROM referencias_biblioteca").fetchone()[0], nuevo)

    def test_usuario_recreado_no_hereda_mensajes(self):
        conversacion, mensaje = self._confirmado()
        self._actualizar("UPDATE usuarios SET activo=0 WHERE id=2")
        with self.assertRaisesRegex(motor.ErrorMotor, "usuario_no_disponible"):
            motor.mensajes(self.b, conversacion)
        self.assertEqual(biblioteca.tarjeta(self.a, conversacion, mensaje), {"estado": "no_disponible"})
        self._actualizar("DELETE FROM usuarios WHERE id=2")
        self._actualizar("INSERT INTO usuarios(id,usuario,nombre,password_hash,rol,departamento) "
                         "VALUES (2,'otro','Otro','ficticio','editor','Tesorería')")
        with conectar() as db:
            nuevo = db.execute("SELECT mensajeria_ref FROM usuarios WHERE id=2").fetchone()[0]
        self.assertNotEqual(nuevo, self.b)
        self.assertEqual(biblioteca.tarjeta(nuevo, conversacion, mensaje), {"estado": "no_disponible"})
        self.assertEqual(motor.conversaciones(nuevo), [])

    def test_dos_envios_y_edicion_concurrente(self):
        entrar, salir, escritor = Event(), Event(), Event()
        abrir = biblioteca._abrir_original

        def detener(*args):
            resultado = abrir(*args)
            entrar.set()
            if not salir.wait(30):
                raise AssertionError("El envío no se reanudó")
            return resultado

        def editar():
            escritor.set()
            self._actualizar("UPDATE documentos SET titulo='Editado', version=version+1 WHERE id=1")

        with ThreadPoolExecutor(3) as pool, patch.object(biblioteca, "_abrir_original", side_effect=detener):
            primero = pool.submit(self._enviar)
            try:
                self.assertTrue(entrar.wait(45))
                edicion = pool.submit(editar)
                self.assertTrue(escritor.wait(10))
                segundo = pool.submit(self._enviar)
                self.assertFalse(edicion.done())
            finally:
                salir.set()
            self.assertEqual(primero.result(timeout=60), segundo.result(timeout=60))
            edicion.result(timeout=60)
        self.assertEqual(motor.cuota(self.a)["envios"], 1)
        self._actualizar("UPDATE usuarios SET departamento='Archivos' WHERE id=2")
        with self.assertRaisesRegex(motor.ErrorMotor, "documento_no_disponible"):
            self._enviar(clave=uuid4().hex)
        self.assertEqual(motor.cuota(self.a)["envios"], 1)

    def test_formato_por_contenido_y_original_manipulado(self):
        self._crear_documento(2, sufijo=".pdf", datos=b"ficticio sin estructura PDF")
        chat, mensaje = self._confirmado(referencia=self._ref(2), modalidad="visualizar_y_descargar")
        tarjeta = biblioteca.tarjeta(self.a, chat, mensaje)
        self.assertIsNone(tarjeta["formato"])
        self.assertEqual(tarjeta["acciones"], ["descargar"])
        self._actualizar("UPDATE documentos SET nombre_guardado='../ruta-reservada' WHERE id=1")
        with self.assertRaisesRegex(motor.ErrorMotor, "^documento_no_disponible$"):
            self._enviar(clave=uuid4().hex)

    def test_escrituras_documentales_que_ganan_la_carrera(self):
        # Cada escritor reserva la base principal antes del envío. El envío
        # debe ver el resultado confirmado, incluso si ya se inició.
        ref = self._ref()
        casos = (
            ("UPDATE documentos SET eliminado_en='2026-01-01' WHERE id=1", False),
            ("UPDATE documentos SET eliminado_en=NULL WHERE id=1", True),
            ("UPDATE documentos SET departamento='Archivos' WHERE id=1", False),
            ("UPDATE documentos SET departamento='Tesorería' WHERE id=1", True),
            ("DELETE FROM documentos WHERE id=1", False),
        )
        for sentencia, permitido in casos:
            conectado = Event()

            @contextmanager
            def reservar(evento=conectado):
                with conectar() as db:
                    evento.set()
                    yield db

            with (
                self.subTest(sentencia=sentencia),
                ThreadPoolExecutor(1) as pool,
                patch.object(rec, "conectar_documental", reservar),
            ):
                with conectar() as principal:
                    principal.execute("BEGIN IMMEDIATE")
                    principal.execute(sentencia)
                    futuro = pool.submit(self._enviar, referencia=ref, clave=uuid4().hex)
                    self.assertTrue(conectado.wait(45))
                    self.assertFalse(futuro.done())
                if permitido:
                    self.assertIsNotNone(futuro.result(timeout=60))
                else:
                    with self.assertRaisesRegex(motor.ErrorMotor, "^documento_no_disponible$"):
                        futuro.result(timeout=60)
        self.assertEqual(motor.cuota(self.a)["envios"], 2)

    def test_z_restauracion_de_generacion_y_documento_ausente(self):
        antes = respaldo.crear_respaldo(RAIZ / "antes.zip")
        self._crear_documento(2)
        conversacion, mensaje = self._confirmado(referencia=self._ref(2))
        respaldo.restaurar_respaldo(antes)
        self.assertEqual(biblioteca.tarjeta(self.a, conversacion, mensaje), {"estado": "no_disponible"})
        with self.assertRaisesRegex(motor.ErrorMotor, "identidad_no_reconciliada"):
            self._enviar(clave=uuid4().hex)
        informe = rec.diagnosticar()
        self.assertEqual(informe["estado"], "generacion_incompatible")
        self.assertEqual(rec.reconciliar(informe["confirmacion"])["estado"], "identidad_coherente")
        self.assertEqual(biblioteca.tarjeta(self.b, conversacion, mensaje), {"estado": "no_disponible"})
        self.assertEqual(motor.mensajes(self.b, conversacion)[0]["id"], mensaje)
        self._enviar(clave=uuid4().hex)


if __name__ == "__main__":
    unittest.main(verbosity=2)
