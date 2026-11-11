"""Datos de diagnóstico aptos para consola, sin mensajes ni argumentos privados."""

from traceback import extract_tb


def detalle_error(error):
    partes = []
    while error is not None:
        traza = extract_tb(error.__traceback__, limit=-1)
        operacion = traza[-1].name if traza else "sin_traza"
        codigos = " ".join(
            f"{campo}={valor}" for campo in ("errno", "winerror", "returncode", "timeout")
            if isinstance((valor := getattr(error, campo, None)), (int, float))
        )
        partes.append(f"{type(error).__name__} operación={operacion}" + (f" {codigos}" if codigos else ""))
        error = error.__cause__
    return " <- ".join(partes)
