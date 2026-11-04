from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.actividad import ACCIONES, RESULTADOS
from app.database import conectar
from app.plantillas import templates
from app.seguridad import requiere_permiso
from app.utilidades import fecha_valida

# Solo los administradores pueden ver el registro
router = APIRouter(dependencies=[Depends(requiere_permiso("actividad"))])

POR_PAGINA = 50


@router.get("/actividad", response_class=HTMLResponse)
def ver_actividad(
    request: Request,
    usuario: str = "",
    accion: str = "",
    resultado: str = "",
    desde: str = "",
    hasta: str = "",
    p: int = 1,
):
    filtros = {
        "usuario": usuario.strip()[:100],
        "accion": accion if accion in ACCIONES else "",
        "resultado": resultado if resultado in RESULTADOS else "",
        "desde": fecha_valida(desde),
        "hasta": fecha_valida(hasta),
    }

    condiciones = []
    parametros = []

    if filtros["usuario"]:
        condiciones.append("usuario = ? COLLATE NOCASE")
        parametros.append(filtros["usuario"])

    if filtros["accion"]:
        condiciones.append("accion = ?")
        parametros.append(filtros["accion"])

    if filtros["resultado"]:
        condiciones.append("resultado = ?")
        parametros.append(filtros["resultado"])

    if filtros["desde"]:
        condiciones.append("date(fecha, 'localtime') >= ?")
        parametros.append(filtros["desde"])

    if filtros["hasta"]:
        condiciones.append("date(fecha, 'localtime') <= ?")
        parametros.append(filtros["hasta"])

    # "donde" solo une textos fijos escritos aquí; los valores van siempre en parametros
    donde = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""

    with conectar() as conexion:
        total = conexion.execute(
            f"SELECT COUNT(*) AS total FROM actividad{donde}",
            parametros,
        ).fetchone()["total"]

        total_paginas = max(1, ceil(total / POR_PAGINA))
        p = min(max(p, 1), total_paginas)

        registros = conexion.execute(
            f"""
            SELECT id, datetime(fecha, 'localtime') AS fecha, usuario, accion,
                   resultado, entidad, entidad_id, entidad_nombre, detalle, ip
            FROM actividad{donde}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*parametros, POR_PAGINA, (p - 1) * POR_PAGINA],
        ).fetchall()

        usuarios_registrados = [
            fila["usuario"]
            for fila in conexion.execute(
                """
                SELECT DISTINCT usuario FROM actividad
                WHERE usuario IS NOT NULL
                ORDER BY usuario COLLATE NOCASE
                """
            )
        ]

    def enlace(numero: int) -> str:
        consulta = {clave: valor for clave, valor in filtros.items() if valor}
        consulta["p"] = numero
        return "/actividad?" + urlencode(consulta)

    return templates.TemplateResponse(
        request=request,
        name="actividad.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "actividad",
            "registros": registros,
            "filtros": filtros,
            "acciones": ACCIONES,
            "resultados": RESULTADOS,
            "usuarios_registrados": usuarios_registrados,
            "total": total,
            "pagina_actual": p,
            "total_paginas": total_paginas,
            "enlace_anterior": enlace(p - 1) if p > 1 else None,
            "enlace_siguiente": enlace(p + 1) if p < total_paginas else None,
        },
    )
