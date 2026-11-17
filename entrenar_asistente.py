"""Entrena, calibra y evalúa el clasificador de Clippy sobre MiniLM congelado."""

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import sys
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from clippy_corpus import LIMITE_SIMILITUD, frases_cercanas, normalizar
from clippy_intenciones import (
    ARTEFACTO,
    DATOS_CLIPPY,
    DESCONOCIDO,
    MAX_CARACTERES,
    MODELO,
    REVISION,
    MotorIntenciones,
    cargar_minilm,
)

DATOS = DATOS_CLIPPY
PARTES = ("entrenamiento", "calibracion", "evaluacion")
EVALUACION_PREDETERMINADA = "evaluacion_optimizada"


def leer_corpus(ruta, evaluacion=EVALUACION_PREDETERMINADA):
    corpus, huellas = {}, {}
    anteriores = {}
    etiquetas = None
    for parte in PARTES:
        fuente = (ruta / f"{evaluacion if parte == 'evaluacion' else parte}.json").read_bytes()
        datos = json.loads(fuente)
        if not isinstance(datos, dict) or DESCONOCIDO not in datos:
            raise ValueError(f"{parte} debe incluir intenciones y ejemplos de desconocido.")
        if etiquetas is None:
            etiquetas = set(datos)
            if len(etiquetas) < 3:
                raise ValueError("Incluye al menos dos intenciones y la clase desconocido.")
        if set(datos) != etiquetas:
            raise ValueError(f"Las intenciones de {parte} deben coincidir con las de entrenamiento.")
        filas = []
        for etiqueta, frases in datos.items():
            if not re.fullmatch(r"[a-z_]+", etiqueta) or not isinstance(frases, list) or not frases:
                raise ValueError(f"Revisa los ejemplos de {etiqueta} en {parte}.")
            for frase in frases:
                if not isinstance(frase, str) or not 1 <= len(frase.strip()) <= MAX_CARACTERES:
                    raise ValueError(f"Frase inválida en {parte}/{etiqueta}.")
                clave = normalizar(frase)
                if not clave or clave in anteriores:
                    raise ValueError(f"Frase vacía o duplicada en {parte}: {frase!r}.")
                for texto, (origen, original) in anteriores.items():
                    if origen != parte and frases_cercanas(texto, clave):
                        raise ValueError(f"Frases demasiado parecidas entre {origen} y {parte}: {original!r} / {frase!r}.")
                anteriores[clave] = (parte, frase)
                filas.append((frase, etiqueta))
        corpus[parte] = filas
        huellas[parte] = hashlib.sha256(fuente).hexdigest()
    return corpus, huellas


def calibrar(motor, vectores, reales):
    import numpy as np
    from sklearn.metrics import f1_score

    puntuaciones = motor.puntuaciones(vectores)
    mejores = np.argsort(puntuaciones, axis=1)[:, -2:]
    candidatas = np.asarray(motor.clases)[mejores[:, 1]]
    maximas = np.take_along_axis(puntuaciones, mejores[:, 1:], axis=1)[:, 0]
    segundas = np.take_along_axis(puntuaciones, mejores[:, :1], axis=1)[:, 0]
    alcance = motor.puntuaciones_alcance(vectores)
    desconocidas = reales == DESCONOCIDO
    mejor = None
    for umbral_alcance in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        for umbral in (0.12, 0.16, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
            for margen in (0.04, 0.08, 0.12, 0.16):
                aceptada = (alcance >= umbral_alcance) & (maximas >= umbral) & (maximas - segundas >= margen)
                predichas = np.where(aceptada, candidatas, DESCONOCIDO)
                rechazo = float(np.mean(predichas[desconocidas] == DESCONOCIDO))
                f1 = f1_score(reales, predichas, labels=motor.clases, average="macro", zero_division=0)
                # Si ningún candidato alcanza el objetivo, prioriza el mayor rechazo disponible.
                clave = (rechazo >= 0.90, f1 if rechazo >= 0.90 else rechazo, f1,
                         rechazo, umbral_alcance, umbral, margen)
                if mejor is None or clave > mejor:
                    mejor = clave
    _, _, f1, rechazo, motor.umbral_alcance, motor.umbral, motor.margen_minimo = mejor
    return {"f1_macro": f1, "rechazo_desconocidos": rechazo, "umbral_alcance": motor.umbral_alcance}


def evaluar(motor, vectores, frases, reales):
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

    decisiones = motor.clasificar_embeddings(vectores)
    predichas = [decision.intencion for decision in decisiones]
    errores = [
        {"frase": frase, "esperada": str(real), "predicha": d.intencion, "candidata": d.candidata,
         "puntuacion": round(d.puntuacion, 4), "margen": round(d.margen, 4), "motivo": d.motivo}
        for frase, real, d in zip(frases, reales, decisiones, strict=True)
        if real != d.intencion
    ]
    aceptadas = sum(p != DESCONOCIDO for p in predichas)
    correctas_aceptadas = sum(p == r and p != DESCONOCIDO for p, r in zip(predichas, reales, strict=True))
    fuera = [e for e in errores if e["esperada"] == DESCONOCIDO]
    operaciones = {"subida", "editar", "descargar", "gestionar_expedientes", "vincular_documentos",
                   "restaurar", "eliminar_definitivamente", "usuarios", "gestionar_avisos"}
    return {
        "exactitud": accuracy_score(reales, predichas),
        "exactitud_sin_rechazo": accuracy_score(reales, [d.candidata for d in decisiones]),
        "cobertura": aceptadas / len(predichas),
        "precision_aceptadas": correctas_aceptadas / aceptadas if aceptadas else None,
        "desconocidas_aceptadas": len(fuera),
        "errores_hacia_operaciones": [e for e in errores if e["predicha"] in operaciones],
        "metricas": classification_report(reales, predichas, labels=motor.clases, output_dict=True, zero_division=0),
        "matriz_confusion": confusion_matrix(reales, predichas, labels=motor.clases).tolist(),
        "confusiones_frecuentes": [
            {"esperada": a, "predicha": b, "cantidad": n}
            for (a, b), n in Counter((e["esperada"], e["predicha"]) for e in errores).most_common(12)
        ],
        "errores": errores,
    }


def medir_inferencia(frases, artefacto, minilm, hilos, sin_red):
    import subprocess

    comando = [sys.executable, __file__, "--medir", "--salida", str(artefacto), "--hilos", str(hilos)]
    if minilm is not None:
        comando.extend(("--minilm-local", str(minilm)))
    if sin_red:
        comando.append("--sin-red")
    proceso = subprocess.run(comando, input=json.dumps(frases), encoding="utf-8",
                             stdout=subprocess.PIPE, check=True)
    return json.loads(proceso.stdout)


def medir_proceso(args):
    import psutil

    frases = json.load(sys.stdin)
    proceso = psutil.Process()
    mib = 1024**2
    rss_base = proceso.memory_info().rss
    inicio = perf_counter()
    motor = MotorIntenciones.cargar(args.salida, minilm=args.minilm_local, hilos=args.hilos, sin_red=args.sin_red)
    carga = perf_counter() - inicio
    rss_cargado = proceso.memory_info().rss
    for frase in frases[:3]:
        motor.interpretar(frase)
    latencias = []
    rss_max = rss_cargado
    for frase in frases:
        inicio = perf_counter()
        motor.interpretar(frase)
        latencias.append((perf_counter() - inicio) * 1000)
        rss_max = max(rss_max, proceso.memory_info().rss)
    import numpy as np

    info = proceso.memory_info()
    return {
        "cpu": os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or platform.machine(),
        "sistema": platform.platform(), "hilos": args.hilos, "frases": len(frases),
        "carga_segundos": round(carga, 3), "latencia_p50_ms": round(float(np.percentile(latencias, 50)), 2),
        "latencia_p95_ms": round(float(np.percentile(latencias, 95)), 2),
        "rss_base_mib": round(rss_base / mib, 1), "rss_cargado_mib": round(rss_cargado / mib, 1),
        "rss_max_muestreado_mib": round(rss_max / mib, 1),
        "rss_pico_proceso_mib": round(info.peak_wset / mib, 1) if hasattr(info, "peak_wset") else None,
    }


def guardar_json(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporal.replace(ruta)


def guardar_matriz(ruta, informe, clases):
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["real / predicha", *clases])
        for clase, fila in zip(clases, informe["matriz_confusion"], strict=True):
            escritor.writerow([clase, *fila])


def entrenar(args):
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    corpus, huellas = leer_corpus(args.datos, args.evaluacion)
    encoder = cargar_minilm(args.minilm_local, args.hilos, args.sin_red)
    frases, etiquetas, vectores = {}, {}, {}
    for parte, filas in corpus.items():
        frases[parte], etiquetas[parte] = zip(*filas, strict=True)
        etiquetas[parte] = np.asarray(etiquetas[parte])
        print(f"Calculando embeddings de {parte} ({len(filas)} frases).", flush=True)
        vectores[parte] = encoder.encode(list(frases[parte]), batch_size=16, normalize_embeddings=True,
                                        show_progress_bar=False)
    clasificador = LogisticRegression(C=35, class_weight="balanced", max_iter=1000, random_state=42)
    clasificador.fit(vectores["entrenamiento"], etiquetas["entrenamiento"])
    alcance = LogisticRegression(C=12, class_weight="balanced", max_iter=1000, random_state=42)
    alcance.fit(vectores["entrenamiento"], etiquetas["entrenamiento"] != DESCONOCIDO)
    datos = {"version": 1, "modelo": MODELO, "revision": REVISION, "clases": clasificador.classes_.tolist(),
             "coeficientes": clasificador.coef_.tolist(), "interceptos": clasificador.intercept_.tolist(),
             "umbral": 0.0, "margen_minimo": 0.0,
             "alcance": {"coeficientes": alcance.coef_[0].tolist(), "intercepto": float(alcance.intercept_[0]), "umbral": 0.0}}
    motor = MotorIntenciones(encoder, datos)
    calibracion = calibrar(motor, vectores["calibracion"], etiquetas["calibracion"])
    datos.update(umbral=motor.umbral, margen_minimo=motor.margen_minimo)
    datos["alcance"]["umbral"] = motor.umbral_alcance
    informe = evaluar(motor, vectores["evaluacion"], frases["evaluacion"], etiquetas["evaluacion"])
    if args.base:
        base = json.loads(args.base.read_text(encoding="utf-8"))
        if (base.get("version"), base.get("modelo"), base.get("revision"), base.get("clases")) != (
            datos["version"], MODELO, REVISION, datos["clases"]
        ):
            raise ValueError("La línea base debe usar las mismas etiquetas y revisión de MiniLM.")
        informe["linea_base"] = evaluar(MotorIntenciones(encoder, base), vectores["evaluacion"],
                                         frases["evaluacion"], etiquetas["evaluacion"])
    # Coseno como auditoría adicional. Las cercanías semánticas se reportan para revisión humana.
    cosenos = vectores["evaluacion"] @ np.concatenate((vectores["entrenamiento"], vectores["calibracion"])).T
    referencia = (*frases["entrenamiento"], *frases["calibracion"])
    cercanas = [
        {"evaluacion": frase, "referencia": referencia[int(fila.argmax())], "coseno": round(float(fila.max()), 4)}
        for frase, fila in zip(frases["evaluacion"], cosenos, strict=True) if fila.max() >= 0.90
    ]
    guardar_json(args.salida, datos)
    del motor, encoder
    if args.base:
        informe["linea_base"]["cpu"] = medir_inferencia(
            list(frases["evaluacion"]), args.base, args.minilm_local, args.hilos, args.sin_red)
    informe.update(modelo=MODELO, revision=REVISION, clases=datos["clases"], corpus_sha256=huellas,
                   muestras={parte: len(filas) for parte, filas in corpus.items()},
                   dependencias={p: version(p) for p in ("sentence-transformers", "transformers", "torch", "scikit-learn", "numpy")},
                   calibracion={**calibracion, "umbral": datos["umbral"], "margen_minimo": datos["margen_minimo"]},
                   auditoria_similitud={"umbral_textual": LIMITE_SIMILITUD, "coseno_maximo": round(float(cosenos.max()), 4),
                                        "pares_coseno_090": cercanas},
                   cpu=medir_inferencia(list(frases["evaluacion"]), args.salida, args.minilm_local, args.hilos, args.sin_red))
    guardar_json(args.informe, informe)
    guardar_matriz(args.informe.with_name("matriz_confusion.csv"), informe, datos["clases"])
    if args.base:
        guardar_matriz(args.informe.with_name("matriz_confusion_base.csv"), informe["linea_base"], datos["clases"])
    print(f"Exactitud {informe['exactitud']:.1%} · F1 macro {informe['metricas']['macro avg']['f1-score']:.3f}")
    print(f"Informe: {args.informe}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datos", type=Path, default=DATOS)
    parser.add_argument("--evaluacion", default=EVALUACION_PREDETERMINADA, help="Nombre del JSON reservado, sin extensión.")
    parser.add_argument("--base", type=Path, help="Clasificador anterior para evaluar sobre las mismas frases.")
    parser.add_argument("--salida", type=Path, default=ARTEFACTO)
    parser.add_argument("--informe", type=Path, default=ARTEFACTO.with_name("evaluacion.json"))
    parser.add_argument("--minilm-local", type=Path)
    parser.add_argument("--hilos", type=int, default=4)
    parser.add_argument("--sin-red", action="store_true")
    parser.add_argument("--medir", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.medir:
        print(json.dumps(medir_proceso(args)))
    else:
        entrenar(args)


if __name__ == "__main__":
    main()
