"""Eliminación definitiva de documentos de la papelera."""

from pathlib import Path

from fastapi import HTTPException, Request

from app.acceso_documentos import filtro_area_documento
from app.actividad import registrar
from app.configuracion import STORAGE_DIR
from app.database import conectar
from app.eliminaciones import encolar, procesar_tareas


def purgar_documentos_papelera(
    request: Request, storage_dir: Path, ids: list[int] | None = None, *, individual: bool = False
) -> tuple[int, int]:
    """Borra registros autorizados atómicamente y luego sus archivos."""
    if storage_dir.resolve() != STORAGE_DIR.resolve():
        raise ValueError("Directorio de documentos no autorizado")
    filtro, parametros = filtro_area_documento(request.state.usuario)
    with conectar() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        condicion = "eliminado_en IS NOT NULL" + filtro
        valores = list(parametros)
        if ids is not None:
            if not ids:
                return 0, 0
            marcadores = ",".join("?" for _ in ids)
            condicion = f"id IN ({marcadores}) AND " + condicion
            valores = [*ids, *parametros]
        documentos = conexion.execute(
            "SELECT id, titulo, nombre_archivo, nombre_guardado FROM documentos WHERE " + condicion,
            valores,
        ).fetchall()
        if ids is not None and len(documentos) != len(ids):
            raise HTTPException(status_code=404, detail="Uno o más documentos no están disponibles en la papelera.")
        tareas = {documento["id"]: encolar(conexion, "documento", documento["nombre_guardado"]) for documento in documentos}
        conexion.execute("DELETE FROM documentos WHERE " + condicion, valores)

    resultados = procesar_tareas(list(tareas.values()))
    pendientes = 0
    for documento in documentos:
        estado = resultados[tareas[documento["id"]]]
        pendiente = estado not in {"completada", "cancelada"}
        pendientes += int(pendiente)
        detalle = ("eliminación definitiva" if individual else "eliminación permanente desde papelera")
        detalle += f" · archivo: {documento['nombre_archivo']}"
        if pendiente:
            detalle += f" (limpieza física pendiente; tarea {tareas[documento['id']]})"
        registrar(request, "eliminar_definitivo", "fallo" if pendiente else "exito", entidad="documento", entidad_id=documento["id"],
                  entidad_nombre=documento["titulo"], detalle=detalle)
    return len(documentos), pendientes
