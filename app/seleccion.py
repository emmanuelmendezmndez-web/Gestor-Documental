"""Validación común de selecciones de documentos."""


def leer_seleccion(documento_ids: list[int]) -> tuple[list[int], str, str | None]:
    ids = list(dict.fromkeys(documento_ids))
    if not ids:
        return ids, "", "seleccion_vacia"
    if len(ids) > 200:
        return ids, "", "seleccion_exceso"
    return ids, ",".join("?" for _ in ids), None
