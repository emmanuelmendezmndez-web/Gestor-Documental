"""Proceso de laboratorio. Lee frases por stdin y escribe solo diagnósticos locales."""

import hashlib
import json
import logging
import os
import sys
from concurrent.futures import Future
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Thread
from time import perf_counter

from clippy_intenciones import MODELO, REVISION, MotorIntenciones

RAIZ = Path(__file__).resolve().parents[2]
MODELOS = RAIZ / ".clippy-modelos"
SOMBRA = MODELOS / "sombra"


def huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def cargar_extraccion(pesos):
    from app.catalogos import DEPARTAMENTOS
    from app.servicios.clippy_extraccion import ExtraccionSombra

    return ExtraccionSombra(pesos / "spacy-paquetes", DEPARTAMENTOS)


class MotorSombra:
    def __init__(self, pesos=MODELOS, archivo_modo=SOMBRA / "modos.json", extraccion=None):
        tema = pesos / "optimizado" / "clasificador.json"
        minilm = pesos / "minilm"
        self.version_tema = huella(tema)
        self.tematico = MotorIntenciones.cargar(tema, minilm=minilm, hilos=1, sin_red=True)
        self.modo = None
        self.version_modo = None
        self.fallo_modo = "modelo_no_disponible"
        try:
            from app.servicios.clippy_modos import ClasificadorModo

            self.version_modo = huella(archivo_modo)
            self.modo = ClasificadorModo.cargar(
                archivo_modo, modelo=MODELO, revision=REVISION,
                dimension=self.tematico.encoder.get_sentence_embedding_dimension(),
            )
        except (OSError, AttributeError, ImportError, KeyError, TypeError, ValueError):
            if self.version_modo is not None:
                self.fallo_modo = "modelo_incompatible"

        self.extraccion = None
        if os.environ.get("NEXUSGRID_CLIPPY_SPACY") == "1":
            self.extraccion = extraccion if extraccion is not None else cargar_extraccion(pesos)

    def inferir(self, texto):
        inicio = perf_counter()
        vector = self.tematico.encoder.encode([texto], normalize_embeddings=True, show_progress_bar=False)
        codificado = perf_counter()
        tema = self.tematico.clasificar_embeddings(vector)[0]
        tematico = perf_counter()
        modo = {"modo": "abstencion", "candidato": None, "puntuacion": None, "margen": None,
                "motivo": self.fallo_modo}
        if self.modo is not None:
            try:
                modo = asdict(self.modo.clasificar_embeddings(vector)[0])
            except Exception:  # noqa: BLE001 - aísla un fallo experimental del resultado temático
                modo["motivo"] = "fallo_inferencia_modo"
        fin = perf_counter()
        modo["aceptado"] = modo["motivo"] == "aceptada"
        resultado = {"tematico": {**asdict(tema), "aceptado": tema.motivo == "aceptada"}, "modo": modo, "version_tematica": self.version_tema,
                "version_modo": self.version_modo, "revision_minilm": REVISION,
                "latencia_ms": {"minilm": (codificado-inicio)*1000, "tematico": (tematico-codificado)*1000,
                                "modo": (fin-tematico)*1000, "total": (fin-inicio)*1000}}
        if self.extraccion is not None:
            resultado["extraccion_spacy"] = self.extraccion.resumir(texto)
            resultado["latencia_ms"]["total"] = (perf_counter()-inicio)*1000
        return resultado


def preparar_log():
    SOMBRA.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("clippy.sombra")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(RotatingFileHandler(SOMBRA / "diagnostico.jsonl", maxBytes=2_000_000,
                                           backupCount=2, encoding="utf-8"))
    return logger


def iniciar_modelo(extraccion):
    futuro = Future()

    def cargar():
        try:
            futuro.set_result(MotorSombra(extraccion=extraccion))
        except Exception:  # noqa: BLE001 - spaCy y las reglas siguen disponibles
            futuro.set_result(None)

    try:
        Thread(target=cargar, daemon=True, name="carga-minilm").start()
    except RuntimeError:
        futuro.set_result(None)
    return futuro


def procesar(canal):
    logger = None
    motor = None
    extraccion = None
    carga_chat = None
    funcional = os.environ.get("NEXUSGRID_CLIPPY_SPACY_FUNCIONAL") == "1"
    for linea in sys.stdin.buffer:
        solicitud = json.loads(linea)
        if solicitud.get("tipo") == "estado":
            estado = "cargando"
            if motor is not None or (carga_chat is not None and carga_chat.done()):
                disponible = (motor is not None or carga_chat.result() is not None)
                estado = "listo" if disponible and extraccion is not None and extraccion.extractor is not None else "no_disponible"
            canal.write(json.dumps(estado).encode("ascii") + b"\n")
            canal.flush()
            continue
        if solicitud.get("tipo") == "precarga":
            if funcional and carga_chat is None and motor is None:
                try:
                    extraccion = cargar_extraccion(MODELOS)
                except Exception:  # noqa: BLE001 - las reglas del navegador quedan disponibles
                    extraccion = None
                carga_chat = iniciar_modelo(extraccion)
            canal.write(b"ok\n")
            canal.flush()
            continue
        if solicitud.get("tipo") in {"extraccion", "chat"}:
            respuesta = None
            if funcional:
                try:
                    if extraccion is None:
                        extraccion = motor.extraccion if motor and motor.extraccion else cargar_extraccion(MODELOS)
                    if extraccion.extractor is not None:
                        respuesta = extraccion.extractor.extraer(solicitud["texto"])
                except Exception:  # noqa: BLE001 - el intérprete web conserva su ruta normal
                    respuesta = None
                if respuesta is not None and solicitud.get("tipo") == "chat":
                    if motor is None and carga_chat is None:
                        carga_chat = iniciar_modelo(extraccion)
                    if motor is None and carga_chat.done():
                        motor = carga_chat.result()
                    if motor is not None:
                        try:
                            tema = motor.tematico.interpretar(solicitud["texto"])
                            if tema.motivo == "aceptada":
                                respuesta["_intencion"] = tema.intencion
                        except Exception:  # noqa: BLE001 - la extracción permanece disponible
                            respuesta.pop("_intencion", None)
            canal.write(json.dumps(respuesta, ensure_ascii=True).encode("ascii") + b"\n")
            canal.flush()
            continue
        if logger is None:
            logger = preparar_log()
        inicio = perf_counter()
        entrada = {"id_prueba": solicitud["id"], "fecha_utc": datetime.now(UTC).isoformat()}
        try:
            if motor is None:
                motor = carga_chat.result() if carga_chat is not None else MotorSombra(extraccion=extraccion)
                if motor is None:
                    raise RuntimeError("MiniLM no disponible")
            entrada.update(motor.inferir(solicitud["texto"]))
        except Exception:  # noqa: BLE001 - no registra frases, rutas ni excepciones
            entrada.update(tematico=None, modo={"modo": "abstencion", "aceptado": False, "motivo": "fallo_worker"},
                           version_tematica=getattr(motor, "version_tema", None),
                           version_modo=getattr(motor, "version_modo", None),
                           latencia_ms={"total": (perf_counter()-inicio)*1000})
        logger.info(json.dumps(entrada, ensure_ascii=False))
        canal.write(b"ok\n")
        canal.flush()
        if motor is None:
            return 1
    return 0


def main():
    canal = sys.stdout.buffer
    if os.environ.get("NEXUSGRID_CLIPPY_CUSTODIA") == "1":
        canal.write(f"pid {os.getpid()}\n".encode("ascii"))
        canal.flush()
    with redirect_stdout(sys.stderr):
        return procesar(canal)


if __name__ == "__main__":
    raise SystemExit(main())

