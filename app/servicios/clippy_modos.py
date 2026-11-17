"""Inferencia experimental de modos. Opera sobre embeddings y devuelve solo una interpretación."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODOS = ("consulta", "ejecutar_accion", "informacion")
ABSTENCION = "abstencion"


@dataclass(frozen=True)
class ResultadoModo:
    modo: str
    candidato: str
    puntuacion: float
    margen: float
    motivo: str


class ClasificadorModo:
    def __init__(self, datos, *, modelo, revision, dimension):
        if (datos["version"], datos["modelo"], datos["revision"], datos["dimension"]) != (
            1, modelo, revision, dimension
        ) or tuple(datos["clases"]) != MODOS or datos["normalizar_embeddings"] is not True:
            raise ValueError("El artefacto de modos no coincide con el encoder.")
        self.coeficientes = np.asarray(datos["coeficientes"], dtype=np.float64)
        self.interceptos = np.asarray(datos["interceptos"], dtype=np.float64)
        self.umbrales = datos["umbrales"]
        if (self.coeficientes.shape != (len(MODOS), dimension)
                or self.interceptos.shape != (len(MODOS),)
                or not np.isfinite(self.coeficientes).all()
                or not np.isfinite(self.interceptos).all()
                or set(self.umbrales) != {"puntuacion", "margen", "margen_accion"}
                or not all(0 <= x <= 1 for x in self.umbrales.values())):
            raise ValueError("Parámetros de modos inválidos.")

    @classmethod
    def cargar(cls, ruta, **encoder):
        return cls(json.loads(Path(ruta).read_text(encoding="utf-8")), **encoder)

    def puntuar(self, vectores):
        logits = vectores @ self.coeficientes.T + self.interceptos
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        return exp / exp.sum(axis=1, keepdims=True)

    @staticmethod
    def resumen(puntuaciones):
        orden = np.argsort(puntuaciones, axis=1)
        mejor = orden[:, -1]
        segunda = orden[:, -2]
        filas = np.arange(len(puntuaciones))
        maximas = puntuaciones[filas, mejor]
        margenes = maximas - puntuaciones[filas, segunda]
        return np.asarray(MODOS)[mejor], maximas, margenes

    @staticmethod
    def aceptar(candidatos, puntuaciones, margenes, umbrales):
        minimo = np.where(candidatos == "ejecutar_accion",
                          max(umbrales["margen"], umbrales["margen_accion"]), umbrales["margen"])
        return (puntuaciones >= umbrales["puntuacion"]) & (margenes >= minimo)

    def clasificar_embeddings(self, vectores):
        candidatos, puntuaciones, margenes = self.resumen(self.puntuar(vectores))
        aceptadas = self.aceptar(candidatos, puntuaciones, margenes, self.umbrales)
        return [
            ResultadoModo(str(candidato) if acepta else ABSTENCION, str(candidato), float(puntuacion),
                          float(margen), "aceptada" if acepta else "puntuacion_o_margen_insuficiente")
            for candidato, puntuacion, margen, acepta in zip(candidatos, puntuaciones, margenes, aceptadas, strict=True)
        ]


def interpretar_compartido(texto, tematico, secundario, *, max_caracteres):
    """Conecta los dos lectores con el mismo vector. No despacha operaciones."""
    if not isinstance(texto, str):
        raise TypeError("La frase debe ser texto.")
    texto = texto.strip()
    if not texto or len(texto) > max_caracteres:
        return tematico.interpretar(texto), None
    vectores = tematico.encoder.encode([texto], normalize_embeddings=True, show_progress_bar=False)
    return tematico.clasificar_embeddings(vectores)[0], secundario.clasificar_embeddings(vectores)[0]

