"""Gestiona el trabajador local de Clippy y las observaciones en modo sombra."""

import json
import logging
import os
import subprocess
from concurrent.futures import Future
from contextlib import suppress
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from uuid import uuid4

from app.parada_siged import custodiar_proceso

MAX_TEXTO = 300
MAX_CUERPO = 4096
ESTADOS_MINILM = frozenset({"cargando", "listo", "no_disponible"})
logger = logging.getLogger("gestor")


def _leer_ids(variable):
    ids = [s.strip() for s in os.environ.get(variable, "").split(",")]
    if all(1 <= len(s) <= 19 and s.isascii() and s.isdecimal() and 0 < int(s) < 2**63 for s in ids):
        return frozenset(map(int, ids))
    return frozenset()


class ObservadorSombra:
    def __init__(self, raiz: Path, *, usuarios: frozenset[int], usuarios_extraccion=frozenset(), extraccion_global=False):
        self.raiz = raiz
        self.usuarios = usuarios
        self.usuarios_extraccion = usuarios_extraccion
        self.extraccion_global = extraccion_global
        self._estado = Lock()
        self._ocupado = Lock()
        self._proceso = None
        self._liberar_custodia = None
        self._cerrado = False
        self._reintentar = 0.0
        self._estado_minilm = "cargando"
        self._siguiente_sondeo = 0.0

    @classmethod
    def desde_entorno(cls, raiz: Path):
        usuarios = _leer_ids("NEXUSGRID_CLIPPY_SOMBRA_USUARIOS") if os.environ.get("NEXUSGRID_CLIPPY_SOMBRA") == "1" else frozenset()
        extraccion_activa = os.environ.get("NEXUSGRID_CLIPPY_SPACY_FUNCIONAL") == "1"
        extraccion = _leer_ids("NEXUSGRID_CLIPPY_SPACY_USUARIOS") if extraccion_activa else frozenset()
        global_activa = extraccion_activa and os.environ.get("NEXUSGRID_CLIPPY_SPACY_USUARIOS", "").strip() == "*"
        return cls(raiz, usuarios=usuarios, usuarios_extraccion=extraccion, extraccion_global=global_activa)

    def autoriza_extraccion(self, usuario):
        return bool(usuario and (self.extraccion_global or usuario["id"] in self.usuarios_extraccion))

    def precargar(self):
        if self.extraccion_global or self.usuarios_extraccion:
            self._iniciar_trabajo("", tipo="precarga")

    def estado_modelo(self):
        with self._estado:
            proceso = self._proceso
            ahora = monotonic()
            if self._cerrado or (proceso is not None and proceso.poll() is not None):
                return "no_disponible"
            estado = self._estado_minilm
            sondear = proceso is not None and estado == "cargando" and ahora >= self._siguiente_sondeo
            if sondear:
                self._siguiente_sondeo = ahora + 2
        if sondear:
            self._iniciar_trabajo("", tipo="estado")
        return estado

    def extraer(self, texto, *, chat=False):
        futuro = Future()
        tipo = "chat" if chat else "extraccion"
        return futuro if self._iniciar_trabajo(texto, tipo=tipo, futuro=futuro) else None

    def autorizado(self, usuario):
        return bool(self.usuarios and usuario and usuario["rol"] == "admin" and usuario["id"] in self.usuarios)

    def observar(self, texto: str):
        self._iniciar_trabajo(texto, tipo="sombra")

    def _iniciar_trabajo(self, texto, *, tipo, futuro=None):
        if not self._ocupado.acquire(blocking=False):
            return False
        try:
            Thread(target=self._enviar, args=(texto, tipo, futuro), daemon=True, name="clippy-sombra").start()
        except RuntimeError:
            self._ocupado.release()
            return False
        return True

    def _iniciar(self):
        ejecutable = self.raiz / ".venv-clippy313" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not ejecutable.is_file():
            raise FileNotFoundError("Entorno de Clippy no instalado")
        entorno = {k: v for k, v in os.environ.items()
                   if k.upper() not in {"PYTHONPATH", "PYTHONHOME"} and not k.upper().startswith(("GESTOR_", "NEXUSGRID_", "SIGED_"))}
        entorno.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                       OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        opciones_windows = 0
        if os.name == "nt":
            entorno["NEXUSGRID_CLIPPY_CUSTODIA"] = "1"
            opciones_windows = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        if os.environ.get("NEXUSGRID_CLIPPY_SPACY") == "1":
            entorno["NEXUSGRID_CLIPPY_SPACY"] = "1"
        if self.extraccion_global or self.usuarios_extraccion:
            entorno["NEXUSGRID_CLIPPY_SPACY_FUNCIONAL"] = "1"
        return subprocess.Popen(
            [str(ejecutable), "-B", "-m", "app.servicios.clippy_sombra_worker"],
            cwd=self.raiz, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=entorno, creationflags=opciones_windows,
        )

    def _custodiar(self, proceso):
        if os.name != "nt":
            return True
        # El PID del intérprete real puede ser distinto del PID del lanzador del venv.
        saludo = proceso.stdout.readline(64).split()
        if len(saludo) != 2 or saludo[0] != b"pid" or not saludo[1].isdigit():
            raise OSError("El trabajador de Clippy no confirmó su PID")
        liberar = custodiar_proceso(int(saludo[1]))
        with self._estado:
            if self._proceso is proceso:
                self._liberar_custodia = liberar
                return True
        liberar()
        return False

    def _enviar(self, texto, tipo, futuro):
        proceso = None
        resultado = None
        try:
            with self._estado:
                if self._cerrado or monotonic() < self._reintentar:
                    return
                nuevo = self._proceso is None or self._proceso.poll() is not None
                if nuevo:
                    if tipo == "estado":
                        return
                    if self._liberar_custodia is not None:
                        self._liberar_custodia()
                        self._liberar_custodia = None
                    self._proceso = self._iniciar()
                    self._estado_minilm = "cargando"
                    self._siguiente_sondeo = 0.0
                proceso = self._proceso
            if nuevo and not self._custodiar(proceso):
                return
            mensaje = {"id": uuid4().hex, "texto": texto, "tipo": tipo}
            proceso.stdin.write(json.dumps(mensaje, ensure_ascii=True).encode("ascii") + b"\n")
            proceso.stdin.flush()
            respuesta = proceso.stdout.readline(65536)
            if tipo == "estado":
                estado = json.loads(respuesta)
                if not isinstance(estado, str) or estado not in ESTADOS_MINILM:
                    raise ValueError("Estado de MiniLM inválido")
                with self._estado:
                    if self._proceso is proceso:
                        self._estado_minilm = estado
            elif futuro is not None and respuesta.endswith(b"\n"):
                resultado = json.loads(respuesta)
            elif respuesta != b"ok\n":
                raise OSError("Proceso de Clippy interrumpido")
        except (OSError, ValueError):
            with self._estado:
                activo = not self._cerrado
                self._estado_minilm = "no_disponible"
                self._reintentar = monotonic() + 30
                retirar = proceso is not None and self._proceso is proceso
                if retirar:
                    self._proceso = None
                    liberar, self._liberar_custodia = self._liberar_custodia, None
            if retirar:
                self._detener(proceso, liberar)
            if activo:
                logger.warning("No se pudo comunicar con el trabajador local de Clippy. El gestor conserva la ayuda por reglas.")
        finally:
            self._ocupado.release()
            if futuro is not None:
                futuro.set_result(resultado)

    @staticmethod
    def _detener(proceso, liberar_custodia):
        try:
            try:
                proceso.stdin.close()
            except (OSError, ValueError):
                pass
            proceso.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            if liberar_custodia is not None:
                liberar_custodia()
                liberar_custodia = None
            try:
                proceso.terminate()
                proceso.wait(timeout=0.7)
            except (OSError, subprocess.TimeoutExpired):
                with suppress(OSError, subprocess.TimeoutExpired):
                    proceso.kill()
                    proceso.wait(timeout=0.4)
        finally:
            if liberar_custodia is not None:
                liberar_custodia()

    def cerrar(self):
        with self._estado:
            self._cerrado = True
            proceso, self._proceso = self._proceso, None
            liberar, self._liberar_custodia = self._liberar_custodia, None
        if proceso is not None:
            self._detener(proceso, liberar)
