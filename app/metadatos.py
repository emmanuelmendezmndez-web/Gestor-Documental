"""Limpieza y validación de datos de documentos."""

from datetime import date

from app.catalogos import CATEGORIAS, DEPARTAMENTOS


def limpiar_metadatos(
    titulo: str,
    categoria: str,
    descripcion: str,
    numero_oficio: str,
    departamento: str,
    fecha_documento: str,
    autor: str,
):
    """Devuelve los datos validados o el código del error encontrado."""
    datos = {
        "titulo": titulo.strip(),
        "categoria": categoria,
        "descripcion": descripcion.strip(),
        "numero_oficio": numero_oficio.strip(),
        "departamento": departamento,
        "fecha_documento": fecha_documento.strip(),
        "autor": autor.strip(),
    }

    if (
        not datos["titulo"]
        or len(datos["titulo"]) > 200
        or len(datos["descripcion"]) > 2000
        or len(datos["numero_oficio"]) > 60
        or len(datos["autor"]) > 100
    ):
        return None, "campos"

    if datos["categoria"] not in CATEGORIAS:
        return None, "categoria"

    if datos["departamento"] and datos["departamento"] not in DEPARTAMENTOS:
        return None, "departamento"

    if datos["fecha_documento"]:
        try:
            datos["fecha_documento"] = date.fromisoformat(
                datos["fecha_documento"]
            ).isoformat()
        except ValueError:
            return None, "fecha"

    return datos, None
