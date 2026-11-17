"""Consulta documental compartida por Biblioteca y Clippy."""

from app.acceso_documentos import condicion_area_documento
from app.database import normalizar_texto
from app.ordenes_biblioteca import EXPR_FECHA
from app.utilidades import escapar_like


def criterios_documentales(usuario, filtros, *, registro=None, folio=""):
    condiciones = ["eliminado_en IS NULL"]
    parametros = []
    area, valores = condicion_area_documento(usuario)
    if area:
        condiciones.append(area)
        parametros.extend(valores)
    for palabra in normalizar_texto(filtros.get("buscar", "")).split()[:8]:
        termino = f"%{escapar_like(palabra)}%"
        condiciones.append(
            "(normalizar(titulo) LIKE ? ESCAPE '\\' "
            "OR normalizar(nombre_archivo) LIKE ? ESCAPE '\\' "
            "OR normalizar(descripcion) LIKE ? ESCAPE '\\')"
        )
        parametros.extend((termino,) * 3)
    for campo in ("categoria", "departamento"):
        if filtros.get(campo):
            condiciones.append(f"{campo} = ?")
            parametros.append(filtros[campo])
    for campo, columna in (("oficio", "numero_oficio"), ("autor", "autor")):
        if filtros.get(campo):
            condiciones.append(f"normalizar({columna}) LIKE ? ESCAPE '\\'")
            parametros.append(f"%{escapar_like(normalizar_texto(filtros[campo]))}%")
    for campo, operador in (("desde", ">="), ("hasta", "<=")):
        if filtros.get(campo):
            condiciones.append(f"{EXPR_FECHA} {operador} ?")
            parametros.append(filtros[campo])
    if registro is not None:
        condiciones.append("id = ?")
        parametros.append(registro)
    if folio:
        condiciones.append("(normalizar(numero_oficio) = ? OR CAST(id AS TEXT) = ?)")
        parametros.extend((normalizar_texto(folio), folio))
    return " WHERE " + " AND ".join(condiciones), parametros

