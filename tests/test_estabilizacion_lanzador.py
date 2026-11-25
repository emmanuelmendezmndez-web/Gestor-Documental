"""Regresiones del diagnóstico de mantenimiento y el cierre por señal."""
import asyncio
import os
import signal
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import arranque
from app.mensajeria import limpieza_adjuntos as limpieza


class MantenimientoTest(unittest.IsolatedAsyncioTestCase):
    async def test_dos_fallos_recuperacion_y_siguiente_lote(self):
        detener = asyncio.Event()
        esperas = []
        estados = [
            limpieza.motor.ErrorMotor("reloj_retrocedio"),
            limpieza.motor.ErrorMotor("ruta/privada/ficticia.pdf"),
            {"aplazados": 1, "sin_evidencia": 0},
            {"aplazados": 0, "sin_evidencia": 0},
        ]

        async def avanzar(corutina, timeout):
            corutina.close()
            esperas.append(timeout)
            if len(esperas) == len(estados):
                detener.set()
            raise TimeoutError

        with (
            patch.object(limpieza, "limpiar", side_effect=estados) as revisar,
            patch.object(asyncio, "wait_for", avanzar),
            self.assertLogs(limpieza.logger, level="INFO") as registro,
        ):
            await limpieza.vigilar(detener)
        self.assertEqual(esperas, [60] * 4)
        self.assertEqual(revisar.call_count, 4)
        self.assertEqual(len(registro.records), 5)
        for numero, codigo in enumerate(("reloj_retrocedio", "error_motor_no_catalogado"), 1):
            fecha, pid, observado, fallos = registro.records[numero-1].args
            self.assertIsNotNone(datetime.fromisoformat(fecha).tzinfo)
            self.assertEqual((pid, observado, fallos), (os.getpid(), codigo, numero))
        self.assertNotIn("privada", str(registro.output))
        self.assertIn("recuperada tras 2 fallos", registro.output[2])
        self.assertIn("objetos aplazados", registro.output[3])
        self.assertIn("completada", registro.output[4])

    async def test_no_oculta_errores_inesperados(self):
        with patch.object(limpieza, "limpiar", side_effect=RuntimeError("ficticio")), self.assertRaises(RuntimeError):
            await limpieza.vigilar(asyncio.Event())


class ParadaTest(unittest.TestCase):
    def test_solo_consume_sigint_tras_cierre_completo(self):
        for caso in ("normal", "sin_arrancar", "sin_senal", "doble", "forzado", "lifespan",
                     "error_lifespan", "incompleto", "plazo", "tarea", "conexion"):
            with self.subTest(caso=caso):
                fin = asyncio.Event()
                if caso != "incompleto":
                    fin.set()
                servidor = SimpleNamespace(
                    run=Mock(side_effect=KeyboardInterrupt), started=caso != "sin_arrancar",
                    _captured_signals=[] if caso == "sin_senal" else [signal.SIGINT] * (2 if caso == "doble" else 1),
                    force_exit=caso == "forzado", drenaje_completo=caso != "plazo",
                    lifespan=SimpleNamespace(shutdown_event=fin, error_occurred=caso == "error_lifespan",
                                             shutdown_failed=caso == "lifespan"),
                    server_state=SimpleNamespace(tasks=caso == "tarea", connections=caso == "conexion"),
                )
                if caso == "normal":
                    self.assertTrue(arranque._ejecutar_servidor(servidor, None))
                else:
                    with self.assertRaises(KeyboardInterrupt):
                        arranque._ejecutar_servidor(servidor, None)
