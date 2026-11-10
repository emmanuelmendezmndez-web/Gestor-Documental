"""Bloqueo de uso funcional durante la fase de reconciliación administrativa."""


class IdentidadNoVerificada(RuntimeError):
    """La identidad histórica aún no puede vincularse con la base documental."""


def exigir_identidad_verificada() -> None:
    """La reconciliación administrativa no habilita operaciones de usuario."""
    raise IdentidadNoVerificada(
        "Mensajería permanece deshabilitada para usuarios"
    )
