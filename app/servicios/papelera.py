"""Eliminación definitiva de documentos de la papelera."""

from pathlib import Path

from fastapi import HTTPException, Request

from app.acceso_documentos import filtro_area_documento
from app.actividad import registrar
from app.configuracion import STORAGE_DIR
from app.eliminaciones import encolar, procesar_tareas
from app.operaciones_documentales import transaccion_documental


def purgar_documentos_papelera(
    request: Request, storage_dir: Path, ids: list[int] | None = None, *, individual: bool = False
) -> tuple[int, int]:
    """Borra registros autorizados atómicamente y luego sus archivos."""
    if storage_dir.resolve() != STORAGE_DIR.resolve():
        raise ValueError("Directorio de documentos no autorizado")
    with transaccion_documental(request, "eliminar") as (conexion, usuario):
        if ids is None and usuario["rol"] != "admin":
            raise HTTPException(status_code=403, detail="Solo un administrador puede vaciar la papelera.")
        filtro, parametros = filtro_area_documento(usuario)
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
        cambio = conexion.execute("DELETE FROM documentos WHERE " + condicion, valores)
        if cambio.rowcount != len(documentos):
            raise HTTPException(status_code=409, detail="La selección cambió. Actualiza la página.")
        for documento in documentos:
            registrar(request, "eliminar_definitivo", "fallo", entidad="documento", entidad_id=documento["id"],
                      entidad_nombre=documento["titulo"],
                      detalle=f"registro eliminado; limpieza física pendiente; tarea {tareas[documento['id']]}",
                      conexion=conexion)

    resultados = procesar_tareas(list(tareas.values()))
    pendientes = 0
    for documento in documentos:
        estado = resultados[tareas[documento["id"]]]
        pendiente = estado not in {"completada", "cancelada"}
        pendientes += int(pendiente)
    return len(documentos), pendientes
