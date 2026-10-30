"""Descripción de cambios para el registro de actividad."""

CAMPOS_COMPARABLES = [
    ("titulo", "título"),
    ("categoria", "categoría"),
    ("numero_oficio", "n.º de oficio"),
    ("departamento", "departamento"),
    ("fecha_documento", "fecha del documento"),
    ("autor", "autor"),
]


def describir_cambios(anterior, datos: dict) -> list[str]:
    """Describe los cambios sin incluir el contenido de la descripción."""
    cambios = []
    for campo, etiqueta in CAMPOS_COMPARABLES:
        antes = anterior[campo] or ""
        despues = datos[campo] or ""
        if antes != despues:
            cambios.append(f"{etiqueta}: «{antes or '—'}» → «{despues or '—'}»")

    if (anterior["descripcion"] or "") != datos["descripcion"]:
        cambios.append("descripción modificada")

    return cambios
