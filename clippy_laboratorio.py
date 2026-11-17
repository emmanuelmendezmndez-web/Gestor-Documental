"""Registro local, revisión humana e incorporación explícita de ejemplos."""

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from clippy_corpus import frases_cercanas, normalizar

DESCONOCIDO = "desconocido"


@contextmanager
def bloquear(ruta):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.with_suffix(ruta.suffix + ".lock").open("a+b") as archivo:
        archivo.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(archivo.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(archivo.fileno(), fcntl.LOCK_EX)
        yield


def escribir_json(ruta, datos):
    contenido = json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with NamedTemporaryFile(dir=ruta.parent, prefix=ruta.name + ".", suffix=".tmp", delete=False) as archivo:
        temporal = Path(archivo.name)
        try:
            archivo.write(contenido.encode("utf-8"))
            archivo.close()
            temporal.replace(ruta)
        finally:
            temporal.unlink(missing_ok=True)


class Laboratorio:
    def __init__(self, ruta):
        self.ruta = Path(ruta).resolve()

    def leer(self):
        if not self.ruta.exists():
            return []
        datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        if not isinstance(datos, dict) or datos.get("version_laboratorio") != 1 or not isinstance(datos.get("frases"), list):
            raise ValueError("El archivo indicado no es un registro del laboratorio.")
        return datos["frases"]

    def _guardar(self, frases):
        escribir_json(self.ruta, {"version_laboratorio": 1, "frases": frases})

    def capturar(self, frase, modelo):
        registro = {
            "id": uuid4().hex, "frase": frase, "fecha": datetime.now(UTC).isoformat(),
            "modelo": str(modelo), "prediccion": None, "etiqueta": None, "estado": "pendiente",
        }
        with bloquear(self.ruta):
            frases = self.leer()
            frases.append(registro)
            self._guardar(frases)
        return registro

    def actualizar(self, registro, **cambios):
        with bloquear(self.ruta):
            frases = self.leer()
            actual = next(f for f in frases if f["id"] == registro["id"])
            if actual != registro:
                raise ValueError("Otra sesión modificó el ejemplo. Vuelve a abrir la revisión.")
            actual.update(cambios)
            self._guardar(frases)
            registro.update(cambios)

    def incorporar(self, datos, max_caracteres):
        entrenamiento = (datos / "entrenamiento.json").resolve()
        if self.ruta == entrenamiento:
            raise ValueError("El registro debe ser independiente del corpus.")
        with bloquear(self.ruta), bloquear(entrenamiento):
            frases = self.leer()
            aprobadas = [r for r in frases if r["estado"] == "aprobada"]
            if not aprobadas:
                return []
            corpus = json.loads(entrenamiento.read_text(encoding="utf-8"))
            reservadas = {}
            for archivo in datos.glob("*.json"):
                if archivo.resolve() in (entrenamiento, self.ruta):
                    continue
                particion = json.loads(archivo.read_text(encoding="utf-8"))
                for ejemplos in particion.values():
                    for frase in ejemplos:
                        reservadas[normalizar(frase)] = archivo.name

            existentes = {normalizar(f) for ejemplos in corpus.values() for f in ejemplos}
            for registro in aprobadas:
                frase = registro["frase"].strip()
                clave = normalizar(frase)
                etiqueta = registro["etiqueta"]
                motivo = None
                if not clave or len(frase) > max_caracteres or etiqueta not in corpus:
                    motivo = "Frase o intención inválida para el corpus."
                elif clave in existentes or any(frases_cercanas(texto, clave) for texto in existentes):
                    motivo = "Ya hay una frase equivalente en entrenamiento."
                else:
                    reservada = next((archivo for texto, archivo in reservadas.items()
                                      if texto == clave or frases_cercanas(texto, clave)), None)
                    if reservada:
                        motivo = f"Coincide o es demasiado parecida a una frase reservada en {reservada}."
                if motivo:
                    registro.update(estado="omitida", motivo_revision=motivo)
                else:
                    corpus[etiqueta].append(frase)
                    existentes.add(clave)
                    registro.update(estado="incorporada", fecha_incorporacion=datetime.now(UTC).isoformat())

            if any(r["estado"] == "incorporada" for r in aprobadas):
                escribir_json(entrenamiento, corpus)
            self._guardar(frases)
            return aprobadas


def etiquetar(registro, clases):
    while True:
        opcion = input("[S] Sí  [N] Elegir intención  [D] Desconocida  [Enter] Después > ").strip().lower()
        if not opcion:
            return None
        if opcion == "s" and registro["prediccion"]:
            return registro["prediccion"]["intencion"]
        if opcion == "d":
            return DESCONOCIDO
        if opcion == "n":
            for numero, clase in enumerate(clases, 1):
                print(f"  {numero:2}. {clase}")
            seleccion = input("Número o nombre de la intención [Enter para volver] > ").strip().lower()
            if seleccion in clases:
                return seleccion
            if seleccion.isascii() and seleccion.isdecimal() and len(seleccion) <= len(str(len(clases))):
                numero = int(seleccion)
                if 1 <= numero <= len(clases):
                    return clases[numero - 1]
            if not seleccion:
                continue
        print("Elige una opción válida.")


def mostrar_prediccion(registro):
    prediccion = registro["prediccion"]
    if prediccion is None:
        print("Predicción pendiente.")
        return
    print(f"Intención detectada: {prediccion['intencion']}")
    print(f"Puntuación: {prediccion['puntuacion']:.3f}")
    if prediccion["candidata"] and prediccion["candidata"] != prediccion["intencion"]:
        print(f"Candidata rechazada: {prediccion['candidata']}")


def consola(motor, laboratorio, modelo):
    print("CLIPPY | LABORATORIO DE ENTRENAMIENTO")
    print("Escribe una frase. Usa Ctrl+C para salir.")
    while True:
        frase = input("\nFrase > ")
        if not frase.strip():
            continue
        registro = laboratorio.capturar(frase, modelo)
        laboratorio.actualizar(registro, prediccion=asdict(motor.interpretar(frase)))
        mostrar_prediccion(registro)
        etiqueta = etiquetar(registro, motor.clases)
        if etiqueta:
            laboratorio.actualizar(registro, etiqueta=etiqueta, estado="etiquetada")
            print(f"Frase guardada y etiquetada como {etiqueta}.")
        else:
            print("Frase guardada para etiquetar después.")


def revisar(laboratorio, clases):
    pendientes = [r for r in laboratorio.leer() if r["estado"] in ("pendiente", "etiquetada")]
    if not pendientes:
        print("No hay frases pendientes de revisión.")
        return
    for registro in pendientes:
        print(f"\n{registro['fecha']} · {registro['frase']!r}")
        mostrar_prediccion(registro)
        if not registro["etiqueta"]:
            etiqueta = etiquetar(registro, clases)
            if not etiqueta:
                continue
            laboratorio.actualizar(registro, etiqueta=etiqueta, estado="etiquetada")
        while True:
            print(f"Etiqueta: {registro['etiqueta']}")
            opcion = input("[A] Aprobar  [E] Cambiar etiqueta  [R] Rechazar  [Enter] Después > ").strip().lower()
            if not opcion:
                break
            if opcion in ("a", "r"):
                estado = "aprobada" if opcion == "a" else "rechazada"
                laboratorio.actualizar(registro, estado=estado, fecha_revision=datetime.now(UTC).isoformat())
                print(f"Frase {estado}.")
                break
            if opcion == "e":
                etiqueta = etiquetar(registro, clases)
                if etiqueta:
                    laboratorio.actualizar(registro, etiqueta=etiqueta)
            else:
                print("Elige una opción válida.")
