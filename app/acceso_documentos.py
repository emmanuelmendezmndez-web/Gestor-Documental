"""Filtro de visibilidad de documentos según la cuenta autenticada."""


def condicion_area_documento(usuario: dict, alias: str = "") -> tuple[str, list[str]]:
    """Devuelve una condición SQL para limitar documentos al área del usuario.

    Los documentos sin departamento son compartidos. El alias, cuando se usa,
    es una constante interna de las consultas (por ejemplo, "d.").
    """
    if usuario.get("rol") == "admin":
        return "", []
    return f"({alias}departamento = ? OR {alias}departamento = '')", [
        usuario.get("departamento") or ""
    ]


def filtro_area_documento(usuario: dict, alias: str = "") -> tuple[str, list[str]]:
    """Condición de área precedida por AND para consultas existentes."""
    condicion, parametros = condicion_area_documento(usuario, alias)
    return (f" AND {condicion}" if condicion else ""), parametros
