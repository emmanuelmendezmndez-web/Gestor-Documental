"""Clasificador experimental de intenciones. Solo devuelve etiquetas y puntuaciones."""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from clippy_laboratorio import DESCONOCIDO, Laboratorio, consola, revisar

MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
RAIZ = Path(__file__).resolve().parent
ARTEFACTO = RAIZ / ".clippy-modelos" / "clasificador.json"
MINILM_LOCAL = ARTEFACTO.parent / "minilm"
MAX_CARACTERES = 300
REGISTRO_LABORATORIO = ARTEFACTO.parent / "laboratorio.json"
DATOS_CLIPPY = RAIZ / "datos" / "clippy"


def cargar_minilm(ruta=None, hilos=4, sin_red=False):
    import torch
    from sentence_transformers import SentenceTransformer

    if hilos < 1:
        raise ValueError("Indica al menos un hilo de CPU.")
    if ruta is None and (MINILM_LOCAL / "model.safetensors").is_file():
        ruta = MINILM_LOCAL
    torch.set_num_threads(hilos)
    return SentenceTransformer(
        str(Path(ruta).resolve()) if ruta else MODELO,
        revision=None if ruta else REVISION,
        device="cpu",
        trust_remote_code=False,
        local_files_only=sin_red or ruta is not None,
        model_kwargs={"use_safetensors": True},
    ).eval()


@dataclass(frozen=True)
class Interpretacion:
    intencion: str
    candidata: str | None
    puntuacion: float
    margen: float
    motivo: str


class MotorIntenciones:
    def __init__(self, encoder, datos):
        import numpy as np

        self.encoder = encoder
        self.clases = datos["clases"]
        self.coef = np.asarray(datos["coeficientes"], dtype=float)
        self.intercepto = np.asarray(datos["interceptos"], dtype=float)
        self.umbral = float(datos["umbral"])
        self.margen_minimo = float(datos["margen_minimo"])
        dimension = encoder.get_sentence_embedding_dimension()
        alcance = datos.get("alcance")
        self.alcance = np.asarray(alcance["coeficientes"], dtype=float) if alcance else None
        self.intercepto_alcance = float(alcance["intercepto"]) if alcance else 0.0
        self.umbral_alcance = float(alcance["umbral"]) if alcance else 0.0
        if (len(self.clases) < 2 or DESCONOCIDO not in self.clases
                or len(set(self.clases)) != len(self.clases)
                or self.coef.shape != (len(self.clases), dimension)
                or self.intercepto.shape != (len(self.clases),)
                or not np.isfinite(self.coef).all() or not np.isfinite(self.intercepto).all()
                or not (0 <= self.umbral <= 1 and 0 <= self.margen_minimo <= 1)):
            raise ValueError("El clasificador guardado contiene parámetros inválidos.")
        if self.alcance is not None and (self.alcance.shape != (dimension,) or not np.isfinite(self.alcance).all()
                or not np.isfinite(self.intercepto_alcance) or not 0 <= self.umbral_alcance <= 1):
            raise ValueError("El filtro de alcance contiene parámetros inválidos.")

    @classmethod
    def cargar(cls, ruta=ARTEFACTO, *, minilm=None, hilos=4, sin_red=False):
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        if (datos.get("version") != 1 or datos.get("modelo") != MODELO
                or datos.get("revision") != REVISION):
            raise ValueError("La versión o el codificador del clasificador no coincide.")
        return cls(cargar_minilm(minilm, hilos, sin_red), datos)

    def interpretar(self, texto):
        if not isinstance(texto, str):
            raise TypeError("La frase debe ser texto.")
        texto = texto.strip()
        if not texto or len(texto) > MAX_CARACTERES:
            motivo = "entrada_vacia" if not texto else "entrada_demasiado_larga"
            return Interpretacion(DESCONOCIDO, None, 0.0, 0.0, motivo)
        vector = self.encoder.encode([texto], normalize_embeddings=True, show_progress_bar=False)
        return self.clasificar_embeddings(vector)[0]

    def puntuaciones(self, vectores):
        import numpy as np

        logits = vectores @ self.coef.T + self.intercepto
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        return exp / exp.sum(axis=1, keepdims=True)

    def puntuaciones_alcance(self, vectores):
        import numpy as np

        if self.alcance is None:
            return np.ones(len(vectores))
        logits = vectores @ self.alcance + self.intercepto_alcance
        return 1 / (1 + np.exp(-np.clip(logits, -500, 500)))

    def clasificar_embeddings(self, vectores):
        return [self.decidir(fila, alcance) for fila, alcance in
                zip(self.puntuaciones(vectores), self.puntuaciones_alcance(vectores), strict=True)]

    def decidir(self, puntuaciones, alcance=1.0):
        mejor, siguiente = puntuaciones.argsort()[-1:-3:-1]
        candidata = self.clases[mejor]
        puntuacion = float(puntuaciones[mejor])
        margen = puntuacion - float(puntuaciones[siguiente])
        if candidata == DESCONOCIDO or alcance < self.umbral_alcance:
            motivo = "fuera_de_alcance"
        elif puntuacion < self.umbral or margen < self.margen_minimo:
            motivo = "incierta"
        else:
            motivo = "aceptada"
        intencion = candidata if motivo == "aceptada" else DESCONOCIDO
        return Interpretacion(intencion, candidata, puntuacion, margen, motivo)


def main():
    parser = argparse.ArgumentParser(description="Interpreta frases con el clasificador experimental de Clippy.")
    parser.add_argument("frases", nargs="*")
    parser.add_argument("--modelo", type=Path, default=ARTEFACTO)
    parser.add_argument("--minilm-local", type=Path)
    parser.add_argument("--hilos", type=int, default=4)
    parser.add_argument("--sin-red", action="store_true")
    parser.add_argument("--registro", type=Path, default=REGISTRO_LABORATORIO, help="JSON local del laboratorio.")
    parser.add_argument("--datos", type=Path, default=DATOS_CLIPPY, help="Directorio del corpus.")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--revisar", action="store_true", help="Etiqueta y aprueba ejemplos guardados.")
    modo.add_argument("--incorporar", action="store_true", help="Agrega al entrenamiento los ejemplos aprobados.")
    args = parser.parse_args()
    if args.frases and (args.revisar or args.incorporar):
        parser.error("--revisar y --incorporar se usan sin frases posicionales.")
    laboratorio = Laboratorio(args.registro)
    if laboratorio.ruta.is_relative_to(args.datos.resolve()):
        parser.error("El registro del laboratorio debe estar fuera del directorio del corpus.")
    try:
        if args.revisar:
            corpus = json.loads((args.datos / "entrenamiento.json").read_text(encoding="utf-8"))
            revisar(laboratorio, sorted(corpus))
        elif args.incorporar:
            resultados = laboratorio.incorporar(args.datos, MAX_CARACTERES)
            incorporadas = sum(r["estado"] == "incorporada" for r in resultados)
            print(f"Incorporadas: {incorporadas}. Omitidas: {len(resultados) - incorporadas}.")
            for registro in resultados:
                if registro["estado"] == "omitida":
                    print(f"{registro['frase']!r} · {registro['motivo_revision']}")
        else:
            motor = MotorIntenciones.cargar(args.modelo, minilm=args.minilm_local, hilos=args.hilos, sin_red=args.sin_red)
            if args.frases:
                for frase in args.frases:
                    print(json.dumps(asdict(motor.interpretar(frase)), ensure_ascii=False))
            else:
                consola(motor, laboratorio, args.modelo.resolve())
    except (EOFError, KeyboardInterrupt):
        print()
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
