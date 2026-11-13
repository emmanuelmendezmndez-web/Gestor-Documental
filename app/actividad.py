import logging

from fastapi import Request

from app.database import conectar

logger = logging.getLogger("gestor")

ACCIONES = {
    "inicio_sesion": "Inicio de sesión",
    "cierre_sesion": "Cierre de sesión",
    "acceso_denegado": "Acceso denegado",
    "consultar": "Consulta de documento",
    "previsualizar": "Vista previa de documento",
    "subir": "Subida de documento",
    "descargar": "Descarga de documento",
    "editar": "Edición de documento",
    "eliminar": "Eliminación de documento",
    "papelera_enviar": "Envío de documento a papelera",
    "restaurar": "Restauración de documento",
    "eliminar_definitivo": "Eliminación definitiva de documento",
    "expediente_crear": "Creación de expediente",
    "expediente_eliminar": "Eliminación de expediente",
    "expediente_vincular": "Vinculación de documento a expediente",
    "aviso_crear": "Publicación de aviso",
    "aviso_estado": "Cambio de estado de aviso",
    "aviso_vencimiento": "Cambio de duración de aviso",
    "aviso_eliminar": "Eliminación de aviso",
    "usuario_crear": "Creación de usuario",
    "usuario_editar": "Edición de usuario",
    "usuario_estado": "Activación o desactivación de usuario",
    "usuario_password": "Restablecimiento de contraseña",
    "usuario_eliminar": "Eliminación de usuario",
    "cuenta_perfil": "Actualización del perfil propio",
    "cuenta_nombre": "Actualización del nombre propio",
    "cuenta_password": "Cambio de contraseña propia",
}

RESULTADOS = {
    "exito": "Éxito",
    "fallo": "Fallo",
    "denegado": "Denegado",
}


def obtener_ip(request: Request | None) -> str | None:
    """IP de la conexión directa. No se confía en cabeceras como X-Forwarded-For,
    porque cualquiera puede falsificarlas."""
    return request.client.host if request and request.client else None


def registrar(
    request: Request | None,
    accion: str,
    resultado: str = "exito",
    *,
    usuario: dict | None = None,
    entidad: str | None = None,
    entidad_id: int | None = None,
    entidad_nombre: str | None = None,
    detalle: str = "",
    conexion=None,
) -> None:
    """Anota una acción en el registro de actividad.

    Si se aporta una conexión, el registro es obligatorio y comparte su
    transacción. Sin conexión es de mejor esfuerzo y solo registra el error."""
    if usuario is None and request is not None:
        usuario = getattr(request.state, "usuario", None)

    def escribir(db):
        db.execute(
                """
                INSERT INTO actividad
                    (usuario_id, usuario, accion, resultado,
                     entidad, entidad_id, entidad_nombre, detalle, ip)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usuario["id"] if usuario else None,
                    usuario["usuario"] if usuario else None,
                    accion,
                    resultado,
                    entidad,
                    entidad_id,
                    entidad_nombre[:200] if entidad_nombre else None,
                    detalle[:500],
                    obtener_ip(request),
                ),
            )

    # Una conexión aportada por la operación hace obligatorio el registro:
    # cualquier error debe alcanzar el gestor de transacciones y revertirla.
    if conexion is not None:
        escribir(conexion)
        return
    try:
        with conectar() as conexion_propia:
            escribir(conexion_propia)
    except Exception:
        logger.exception("No se pudo registrar la actividad (%s)", accion)
