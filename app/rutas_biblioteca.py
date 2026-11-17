"""Rutas de SIGED."""

from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.catalogos import CATEGORIAS, DEPARTAMENTOS
from app.database import conectar
from app.mensajes import AVISOS
from app.ordenes_biblioteca import EXPR_FECHA, ORDEN_PREDETERMINADO, ORDENES
from app.plantillas import templates
from app.seguridad import requiere_permiso
from app.servicios.busqueda_documental import criterios_documentales
from app.utilidades import fecha_valida

POR_PAGINA = 20
router = APIRouter()

@router.get(
    "/",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver"))],
)
def inicio(
    request: Request,
    aviso: str | None = None,
    buscar: str = "",
    categoria: str = "",
    oficio: str = "",
    departamento: str = "",
    autor: str = "",
    desde: str = "",
    hasta: str = "",
    orden: str = ORDEN_PREDETERMINADO,
    p: int = 1,
):
    tipo, mensaje = AVISOS.get(aviso, (None, None))

    filtros = {
        "buscar": buscar.strip()[:200],
        "categoria": categoria if categoria in CATEGORIAS else "",
        "oficio": oficio.strip()[:60],
        "departamento": departamento if departamento in DEPARTAMENTOS else "",
        "autor": autor.strip()[:100],
        "desde": fecha_valida(desde),
        "hasta": fecha_valida(hasta),
        "orden": orden if orden in ORDENES else ORDEN_PREDETERMINADO,
    }

    donde, parametros = criterios_documentales(request.state.usuario, filtros)
    orden_sql = ORDENES[filtros["orden"]][1]

    with conectar() as conexion:
        total = conexion.execute(
            f"SELECT COUNT(*) AS total FROM documentos{donde}",
            parametros,
        ).fetchone()["total"]

        total_paginas = max(1, ceil(total / POR_PAGINA))
        p = min(max(p, 1), total_paginas)

        documentos = conexion.execute(
            f"""
            SELECT id, titulo, nombre_archivo, categoria, numero_oficio,
                   departamento, autor, fecha_documento,
                   {EXPR_FECHA} AS fecha_efectiva
            FROM documentos{donde}
            ORDER BY {orden_sql}
            LIMIT ? OFFSET ?
            """,
            [*parametros, POR_PAGINA, (p - 1) * POR_PAGINA],
        ).fetchall()

    def enlace(numero: int) -> str:
        consulta = {
            clave: valor
            for clave, valor in filtros.items()
            if valor and not (clave == "orden" and valor == ORDEN_PREDETERMINADO)
        }
        consulta["p"] = numero
        return "/?" + urlencode(consulta)

    hay_filtros = any(
        filtros[clave]
        for clave in ("buscar", "categoria", "oficio", "departamento", "autor", "desde", "hasta")
    )
    avanzada_activa = any(
        filtros[clave] for clave in ("oficio", "departamento", "autor", "desde", "hasta")
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "biblioteca",
            "documentos": documentos,
            "categorias": CATEGORIAS,
            "departamentos": DEPARTAMENTOS,
            "ordenes": [(clave, datos[0]) for clave, datos in ORDENES.items()],
            "filtros": filtros,
            "hay_filtros": hay_filtros,
            "avanzada_activa": avanzada_activa,
            "total": total,
            "pagina_actual": p,
            "total_paginas": total_paginas,
            "enlace_anterior": enlace(p - 1) if p > 1 else None,
            "enlace_siguiente": enlace(p + 1) if p < total_paginas else None,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )

