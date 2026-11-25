"""Regresiones del protocolo, estados HTTP y carga, sin modelos ni datos institucionales."""

import io
import json
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from app import asistente
from app.servicios import clippy_sombra_worker as worker
from app.servicios.clippy_sombra import ObservadorSombra


def completado(valor):
    futuro = Future()
    futuro.set_result(valor)
    return futuro


def menciones(estado="aceptada"):
    return {
        "folios": [], "fechas": [], "departamentos": [], "referencias": [], "negaciones": [],
        "_analisis": {"estado": estado, "motivo": "aceptada" if estado == "aceptada" else "baja_confianza",
                      "puntuacion": .85, "margen": .4},
        **({"_intencion": "ajustes"} if estado == "aceptada" else {}),
    }


class EstadoHTTPTest(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(asistente.router)
        def autorizar(request: Request):
            request.state.usuario = {"id": 1, "rol": "lector", "departamento": "Tesorería"}
        self.app.dependency_overrides[asistente.router.dependencies[0].dependency] = autorizar
        self.observador = SimpleNamespace(
            autoriza_extraccion=lambda usuario: True,
            extraer=lambda texto, **opciones: completado(menciones()),
            diagnostico_modelo=lambda: {"estado": "cargando", "fase": "minilm", "spacy_ms": 123},
        )
        self.app.state.clippy_sombra = self.observador
        self.cliente = TestClient(self.app)
        self.addCleanup(self.cliente.close)

    def interpretar(self):
        return self.cliente.post("/asistente/interpretar?chat=true", json={"texto": "¿Cómo ajusto el tema?"})

    def test_aceptacion_y_abstencion_conservan_diagnosticos_distintos(self):
        for estado in ("aceptada", "abstencion"):
            with self.subTest(estado=estado):
                self.observador.extraer = lambda *args, estado=estado, **kwargs: completado(menciones(estado))
                r = self.interpretar()
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.headers["X-Clippy-Estado"], estado)
                self.assertEqual(r.json()["analisis"]["estado"], estado)
                self.assertEqual(r.json()["analisis"]["margen"], .4)
                self.assertEqual("intencion" in r.json(), estado == "aceptada")

    def test_carga_ocupacion_indisponibilidad_y_plazo_se_distinguen(self):
        for estado in ("cargando", "no_disponible"):
            self.observador.extraer = lambda *args, estado=estado, **kwargs: completado({"_analisis": {"estado": estado}})
            r = self.interpretar()
            self.assertEqual(r.status_code, 204)
            self.assertEqual(r.headers["X-Clippy-Estado"], estado)
        self.observador.extraer = lambda *args, **kwargs: None
        self.assertEqual(self.interpretar().headers["X-Clippy-Estado"], "ocupado")
        self.observador.extraer = lambda *args, **kwargs: completado(None)
        self.assertEqual(self.interpretar().headers["X-Clippy-Estado"], "no_disponible")
        self.observador.extraer = lambda *args, **kwargs: Future()
        self.assertEqual(self.interpretar().headers["X-Clippy-Estado"], "tiempo_agotado")

    def test_autorizacion_se_comprueba_antes_de_usar_el_trabajador(self):
        self.observador.autoriza_extraccion = lambda usuario: False
        with patch.object(self.observador, "extraer") as extraer:
            self.assertEqual(self.interpretar().status_code, 404)
            self.assertEqual(self.cliente.get("/asistente/estado-modelo").status_code, 404)
            extraer.assert_not_called()

    def test_estado_muestra_fase_y_tiempos_sin_texto_del_usuario(self):
        r = self.cliente.get("/asistente/estado-modelo")
        self.assertEqual(r.json(), {"estado": "cargando", "fase": "minilm", "spacy_ms": 123})
        self.assertIn("no-store", r.headers["cache-control"])


class ProtocoloTest(unittest.TestCase):
    def crear(self):
        obs = ObservadorSombra(Path("."), usuarios=frozenset(), extraccion_global=True)
        self.addCleanup(obs.cerrar)
        return obs

    def test_cargando_y_cerrado_responden_sin_crear_procesos(self):
        obs = self.crear()
        with patch.object(obs, "_iniciar") as iniciar:
            self.assertEqual(obs.extraer("Una pregunta", chat=True).result()["_analisis"]["estado"], "cargando")
            obs.cerrar()
            self.assertEqual(obs.extraer("Otra pregunta", chat=True).result()["_analisis"]["estado"], "no_disponible")
            iniciar.assert_not_called()

    def test_ocupado_no_crea_otra_carga(self):
        obs = self.crear()
        obs._estado_minilm = "listo"
        obs._ocupado.acquire()
        try:
            with patch.object(obs, "_iniciar") as iniciar:
                self.assertIsNone(obs.extraer("Otra solicitud", chat=True))
                iniciar.assert_not_called()
        finally:
            obs._ocupado.release()

    def test_entorno_ausente_se_registra_y_se_cierra(self):
        with tempfile.TemporaryDirectory() as temporal:
            obs = ObservadorSombra(Path(temporal), usuarios=frozenset())
            obs._ocupado.acquire()
            futuro = Future()
            obs._enviar("Frase ficticia", "chat", futuro)
            self.assertEqual(futuro.result()["_analisis"]["estado"], "no_disponible")
            self.assertEqual(obs.estado_modelo(), "no_disponible")
            self.assertFalse(obs._ocupado.locked())
            obs.cerrar()

    def test_respuesta_de_otra_solicitud_se_rechaza(self):
        obs = self.crear()
        proc = SimpleNamespace(poll=lambda: None, stdin=io.BytesIO(),
                               stdout=io.BytesIO(b'{"id":"otra","datos":{}}\n'))
        obs._proceso = proc
        obs._ocupado.acquire()
        futuro = Future()
        with patch.object(obs, "_detener"):
            obs._enviar("Frase ficticia", "chat", futuro)
        self.assertEqual(futuro.result()["_analisis"]["estado"], "no_disponible")
        self.assertIsNone(obs._proceso)

    def test_id_y_texto_se_corresponden_en_respuestas_sucesivas(self):
        obs = self.crear()
        for texto in ("folio RH-2025-27", "folio TES-2026-15"):
            entrada = io.BytesIO()
            class Respuesta:
                def __init__(self, entrada, texto):
                    self.entrada = entrada
                    self.texto = texto

                def readline(self, limite):
                    solicitud = json.loads(self.entrada.getvalue())
                    return (json.dumps({"id": solicitud["id"], "datos": {
                        "referencia": self.texto, "_analisis": {"estado": "aceptada"}}}) + "\n").encode()
            obs._proceso = SimpleNamespace(poll=lambda: None, stdin=entrada, stdout=Respuesta(entrada,texto))
            obs._ocupado.acquire()
            futuro = Future()
            obs._enviar(texto, "chat", futuro)
            resultado = futuro.result()
            solicitud = json.loads(entrada.getvalue())
            self.assertEqual(resultado["referencia"], solicitud["texto"])
            self.assertEqual(resultado["_analisis"]["solicitud_id"], solicitud["id"])
        obs._proceso = None


class CargaTest(unittest.TestCase):
    def test_precarga_incluye_la_primera_inferencia_antes_de_marcar_listo(self):
        diagnostico = {}
        with patch.object(worker, "MotorSombra") as crear:
            motor = worker.iniciar_modelo(None, diagnostico).result(timeout=2)
            self.assertIs(motor, crear.return_value)
            motor.tematico.interpretar.assert_called_once_with("Preparación de Clippy.")
            self.assertGreaterEqual(diagnostico["calentamiento_ms"], 0)

    def test_fallo_de_carga_identificable_sin_mensaje_sensible(self):
        diagnostico = {}
        with patch.object(worker, "MotorSombra", side_effect=ValueError("ruta confidencial")):
            self.assertIsNone(worker.iniciar_modelo(None, diagnostico).result(timeout=2))
        self.assertEqual(diagnostico["motivo"], "error_carga_ValueError")
        self.assertNotIn("confidencial", json.dumps(diagnostico))
        self.assertGreaterEqual(diagnostico["minilm_ms"], 0)


if __name__ == "__main__":
    unittest.main()
