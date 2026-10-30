"""Eliminación definitiva de documentos de la papelera."""

import logging
from pathlib import Path

from fastapi import HTTPException, Request

from app.acceso_documentos import filtro_area_documento
from app.actividad import registrar
from app.database import conectar

logger = logging.getLogger("gestor")


def purgar_documentos_papelera(
    request: Request, storage_dir: Path, ids: list[int] | None = None, *, individual: bool = False
) -> int:
    """Borra registros autorizados atómicamente y luego sus archivos."""
    filtro, parametros = filtro_area_documento(request.state.usuario)
    with conectar() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        condicion = "eliminado_en IS NOT NULL" + filtro
        valores = list(parametros)
        if ids is not None:
            if not ids:
                return 0
            marcadores = ",".join("?" for _ in ids)
            condicion = f"id IN ({marcadores}) AND " + condicion
            valores = [*ids, *parametros]
        documentos = conexion.execute(
            "SELECT id, titulo, nombre_archivo, nombre_guardado FROM documentos WHERE " + condicion,
            valores,
        ).fetchall()
        if ids is not None and len(documentos) != len(ids):
            raise HTTPException(status_code=404, detail="Uno o más documentos no están disponibles en la papelera.")
        conexion.execute("DELETE FROM documentos WHERE " + condicion, valores)

    for documento in documentos:
        archivo_borrado = True
        try:
            (storage_dir / documento["nombre_guardado"]).unlink(missing_ok=True)
        except OSError:
            archivo_borrado = False
            logger.exception("No se pudo borrar definitivamente el archivo %s", documento["nombre_guardado"])
        detalle = ("eliminación definitiva" if individual else "eliminación permanente desde papelera")
        detalle += f" · archivo: {documento['nombre_archivo']}"
        if individual and not archivo_borrado:
            detalle += " (el archivo no se pudo borrar de storage/)"
        registrar(request, "eliminar_definitivo", entidad="documento", entidad_id=documento["id"],
                  entidad_nombre=documento["titulo"], detalle=detalle)
    return len(documentos)
