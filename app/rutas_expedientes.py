"""Rutas de SIGED."""

import logging
from datetime import date
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.acceso_documentos import filtro_area_documento
from app.actividad import registrar
from app.database import conectar, normalizar_texto
from app.mensajes import AVISOS
from app.plantillas import templates
from app.seleccion import leer_seleccion
from app.utilidades import escapar_like
from app.seguridad import requiere_permiso

logger = logging.getLogger("gestor")
POR_PAGINA = 20
router = APIRouter()

@router.get(
    "/expedientes",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver_expedientes"))],
)
def lista_expedientes(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    filtro_area_documento_sql, parametros_area = filtro_area_documento(
        request.state.usuario, "d."
    )
    with conectar() as conexion:
        expedientes = conexion.execute(
            """
            SELECT e.id, e.folio, e.titulo, e.descripcion,
                   datetime(e.fecha_creacion, 'localtime') AS fecha_creacion,
                   COALESCE(u.nombre, u.usuario) AS creador,
                   COUNT(d.id) AS total_documentos
            FROM expedientes e
            LEFT JOIN usuarios u ON u.id = e.creado_por
            LEFT JOIN expediente_documentos ed ON ed.expediente_id = e.id
            LEFT JOIN documentos d
                   ON d.id = ed.documento_id AND d.eliminado_en IS NULL"""
            + filtro_area_documento_sql
            + """
            GROUP BY e.id
            ORDER BY e.id DESC
            """,
            parametros_area,
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="expedientes.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "biblioteca",
            "expedientes": expedientes,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post(
    "/expedientes",
    dependencies=[Depends(requiere_permiso("gestionar_expedientes"))],
)
def crear_expediente(
    request: Request,
    titulo: str = Form(...),
    descripcion: str = Form(""),
):
    titulo = titulo.strip()
    descripcion = descripcion.strip()
    if not titulo or len(titulo) > 200 or len(descripcion) > 2000:
        return RedirectResponse(url="/expedientes?aviso=expediente_campos", status_code=303)

    try:
        with conectar() as conexion:
            resultado = conexion.execute(
                "INSERT INTO expedientes (titulo, descripcion, creado_por) VALUES (?, ?, ?)",
                (titulo, descripcion, request.state.usuario["id"]),
            )
            expediente_id = resultado.lastrowid
            folio = f"EXP-{date.today().year}-{expediente_id:06d}"
            conexion.execute(
                "UPDATE expedientes SET folio = ? WHERE id = ?",
                (folio, expediente_id),
            )
    except Exception:
        logger.exception("No se pudo crear el expediente")
        return RedirectResponse(url="/expedientes?aviso=error_expediente", status_code=303)

    registrar(
        request,
        "expediente_crear",
        entidad="expediente",
        entidad_id=expediente_id,
        entidad_nombre=folio,
        detalle=titulo,
    )
    return RedirectResponse(
        url=f"/expedientes/{expediente_id}?aviso=expediente_creado",
        status_code=303,
    )


@router.get(
    "/expedientes/{expediente_id}/eliminar",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("gestionar_expedientes"))],
)
def pagina_eliminar_expediente(request: Request, expediente_id: int):
    with conectar() as conexion:
        expediente = conexion.execute(
            "SELECT id, folio, titulo, descripcion FROM expedientes WHERE id = ?",
            (expediente_id,),
        ).fetchone()
    if expediente is None:
        raise HTTPException(status_code=404, detail="Expediente no encontrado.")

    return templates.TemplateResponse(
        request=request,
        name="eliminar_expediente.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "biblioteca",
            "expediente": expediente,
        },
    )


@router.post(
    "/expedientes/{expediente_id}/eliminar",
    dependencies=[Depends(requiere_permiso("gestionar_expedientes"))],
)
def eliminar_expediente(request: Request, expediente_id: int):
    try:
        with conectar() as conexion:
            expediente = conexion.execute(
                "SELECT folio, titulo FROM expedientes WHERE id = ?",
                (expediente_id,),
            ).fetchone()
            if expediente is None:
                raise HTTPException(status_code=404, detail="Expediente no encontrado.")

            # La FK ON DELETE CASCADE elimina solo las asociaciones del expediente;
            # los documentos originales permanecen en la biblioteca.
            conexion.execute("DELETE FROM expedientes WHERE id = ?", (expediente_id,))
    except HTTPException:
        raise
    except Exception:
        logger.exception("No se pudo eliminar el expediente %s", expediente_id)
        return RedirectResponse(
            url="/expedientes?aviso=error_eliminar_expediente",
            status_code=303,
        )

    registrar(
        request,
        "expediente_eliminar",
        entidad="expediente",
        entidad_id=expediente_id,
        entidad_nombre=expediente["folio"],
        detalle=expediente["titulo"],
    )
    return RedirectResponse(url="/expedientes?aviso=expediente_eliminado", status_code=303)


@router.get(
    "/expedientes/{expediente_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver_expedientes"))],
)
def ficha_expediente(
    request: Request,
    expediente_id: int,
    buscar: str = "",
    aviso: str | None = None,
):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    buscar = buscar.strip()[:200]
    filtro_area_documento_sql, parametros_area = filtro_area_documento(
        request.state.usuario, "d."
    )
    with conectar() as conexion:
        expediente = conexion.execute(
            """
            SELECT e.id, e.folio, e.titulo, e.descripcion,
                   datetime(e.fecha_creacion, 'localtime') AS fecha_creacion,
                   COALESCE(u.nombre, u.usuario) AS creador
            FROM expedientes e
            LEFT JOIN usuarios u ON u.id = e.creado_por
            WHERE e.id = ?
            """,
            (expediente_id,),
        ).fetchone()
        if expediente is None:
            raise HTTPException(status_code=404, detail="Expediente no encontrado.")

        documentos_vinculados = conexion.execute(
            """
            SELECT d.id, d.titulo, d.nombre_archivo, d.categoria,
                   d.numero_oficio, d.fecha_documento,
                   datetime(ed.fecha_vinculacion, 'localtime') AS fecha_vinculacion
            FROM expediente_documentos ed
            JOIN documentos d ON d.id = ed.documento_id
            WHERE ed.expediente_id = ? AND d.eliminado_en IS NULL"""
            + filtro_area_documento_sql
            + """
            ORDER BY ed.fecha_vinculacion DESC, d.id DESC
            """,
            [expediente_id, *parametros_area],
        ).fetchall()

        resultados = []
        if buscar:
            termino = f"%{escapar_like(normalizar_texto(buscar))}%"
            resultados = conexion.execute(
                """
                SELECT d.id, d.titulo, d.nombre_archivo, d.categoria,
                       d.numero_oficio, d.fecha_documento
                FROM documentos d
                WHERE d.eliminado_en IS NULL
                """ + filtro_area_documento_sql + """
                  AND (
                    normalizar(d.titulo) LIKE ? ESCAPE '\\'
                    OR normalizar(d.nombre_archivo) LIKE ? ESCAPE '\\'
                    OR normalizar(d.numero_oficio) LIKE ? ESCAPE '\\'
                    OR CAST(d.id AS TEXT) LIKE ? ESCAPE '\\'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM expediente_documentos ed
                    WHERE ed.expediente_id = ? AND ed.documento_id = d.id
                  )
                ORDER BY d.id DESC
                LIMIT 30
                """,
                [*parametros_area, termino, termino, termino, termino, expediente_id],
            ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="expediente.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "biblioteca",
            "expediente": expediente,
            "documentos": documentos_vinculados,
            "buscar": buscar,
            "resultados": resultados,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post(
    "/expedientes/{expediente_id}/documentos",
    dependencies=[Depends(requiere_permiso("gestionar_expedientes"))],
)
def vincular_documentos_masivo(
    request: Request,
    expediente_id: int,
    documento_ids: list[int] = Form(default=[]),
):
    ids, placeholders, error = leer_seleccion(documento_ids)
    if error:
        return RedirectResponse(
            url=f"/expedientes/{expediente_id}?aviso={error}",
            status_code=303,
        )

    filtro_area, parametros_area = filtro_area_documento(request.state.usuario, "d.")
    with conectar() as conexion:
        expediente = conexion.execute(
            "SELECT folio FROM expedientes WHERE id = ?", (expediente_id,)
        ).fetchone()
        if expediente is None:
            raise HTTPException(status_code=404, detail="Expediente no encontrado.")
        documentos = conexion.execute(
            "SELECT d.id, d.titulo FROM documentos d "
            f"WHERE d.id IN ({placeholders}) AND d.eliminado_en IS NULL" + filtro_area,
            [*ids, *parametros_area],
        ).fetchall()
        if len(documentos) != len(ids):
            raise HTTPException(status_code=404, detail="Uno o más documentos no están disponibles.")
        conexion.executemany(
            "INSERT OR IGNORE INTO expediente_documentos "
            "(expediente_id, documento_id, vinculado_por) VALUES (?, ?, ?)",
            [(expediente_id, documento["id"], request.state.usuario["id"]) for documento in documentos],
        )

    for documento in documentos:
        registrar(
            request,
            "expediente_vincular",
            entidad="documento",
            entidad_id=documento["id"],
            entidad_nombre=documento["titulo"],
            detalle=f"expediente {expediente['folio']} (selección múltiple)",
        )
    return RedirectResponse(
        url=f"/expedientes/{expediente_id}?aviso=documentos_vinculados",
        status_code=303,
    )


@router.post(
    "/expedientes/{expediente_id}/documentos/{documento_id}",
    dependencies=[Depends(requiere_permiso("gestionar_expedientes"))],
)
def vincular_documento(
    request: Request,
    expediente_id: int,
    documento_id: int,
):
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)
    with conectar() as conexion:
        expediente = conexion.execute(
            "SELECT folio FROM expedientes WHERE id = ?",
            (expediente_id,),
        ).fetchone()
        if expediente is None:
            raise HTTPException(status_code=404, detail="Expediente no encontrado.")

        documento = conexion.execute(
            "SELECT id, titulo FROM documentos WHERE id = ? AND eliminado_en IS NULL"
            + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()
        if documento is None:
            raise HTTPException(status_code=404, detail="Documento no encontrado en la biblioteca.")

        resultado = conexion.execute(
            """
            INSERT OR IGNORE INTO expediente_documentos
                (expediente_id, documento_id, vinculado_por)
            VALUES (?, ?, ?)
            """,
            (expediente_id, documento_id, request.state.usuario["id"]),
        )

    if resultado.rowcount:
        registrar(
            request,
            "expediente_vincular",
            entidad="documento",
            entidad_id=documento_id,
            entidad_nombre=documento["titulo"],
            detalle=f"expediente {expediente['folio']}",
        )
    return RedirectResponse(
        url=f"/expedientes/{expediente_id}?aviso=documento_vinculado",
        status_code=303,
    )

