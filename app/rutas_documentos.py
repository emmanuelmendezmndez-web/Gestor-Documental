"""Rutas de SIGED."""

import logging
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from app.acceso_documentos import filtro_area_documento
from app.actividad import registrar
from app.archivos import ArchivoInvalido, guardar_en_disco
from app.catalogos import CATEGORIAS, DEPARTAMENTOS
from app.configuracion import STORAGE_DIR
from app.database import conectar
from app.eliminaciones import descartar_generado
from app.ediciones import describir_cambios
from app.metadatos import limpiar_metadatos
from app.mensajes import AVISOS, MOTIVOS_SUBIDA
from app.plantillas import templates
from app.previsualizacion import ArchivoNoPrevisualizable, convertir_office_a_pdf
from app.respuestas_documentos import avisar, avisar_edicion, avisar_eliminacion
from app.seleccion import leer_seleccion
from app.tipos_archivo import EXTENSIONES_PERMITIDAS, TIPOS_ARCHIVO
from app.utilidades import formatear_tamano
from app.seguridad import requiere_permiso

logger = logging.getLogger("gestor")
router = APIRouter()

def fallo_subida(
    request: Request,
    codigo: str,
    titulo: str,
    nombre_archivo: str = "",
) -> RedirectResponse:
    """Anota el intento fallido en el registro y devuelve al formulario."""
    detalle = MOTIVOS_SUBIDA.get(codigo, codigo)
    if nombre_archivo:
        detalle += f" (archivo: {nombre_archivo})"

    registrar(
        request,
        "subir",
        "fallo",
        entidad="documento",
        entidad_nombre=titulo,
        detalle=detalle,
    )
    return avisar(codigo)


@router.get(
    "/subir",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("subir"))],
)
def pagina_subir(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS.get(aviso, (None, None))

    return templates.TemplateResponse(
        request=request,
        name="subir.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "subir",
            "categorias": CATEGORIAS,
            "departamentos": DEPARTAMENTOS,
            "es_admin": request.state.usuario["rol"] == "admin",
            "area_usuario": request.state.usuario.get("departamento", ""),
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post("/subir", dependencies=[Depends(requiere_permiso("subir"))])
def subir(
    request: Request,
    titulo: str = Form(...),
    categoria: str = Form(...),
    descripcion: str = Form(""),
    numero_oficio: str = Form(""),
    departamento: str = Form(""),
    fecha_documento: str = Form(""),
    autor: str = Form(""),
    archivo: UploadFile = File(...),
):
    datos, error = limpiar_metadatos(
        titulo, categoria, descripcion, numero_oficio,
        departamento, fecha_documento, autor,
    )
    if error:
        return fallo_subida(request, error, titulo.strip())

    if request.state.usuario["rol"] != "admin":
        area_usuario = request.state.usuario.get("departamento", "")
        if area_usuario not in DEPARTAMENTOS:
            return fallo_subida(request, "area_usuario", datos["titulo"])
        # Nunca confiar en el área enviada por el formulario del navegador.
        datos["departamento"] = area_usuario

    # Path(...).name descarta cualquier carpeta que venga en el nombre ("../../x.pdf")
    nombre_completo = Path((archivo.filename or "").replace("\\", "/")).name
    extension = Path(nombre_completo).suffix.lower()

    if extension not in EXTENSIONES_PERMITIDAS:
        return fallo_subida(request, "formato", datos["titulo"], nombre_completo[:260])

    nombre_original = nombre_completo[:260]
    nombre_guardado = f"{uuid4().hex}{extension}"
    destino = STORAGE_DIR / nombre_guardado

    try:
        tamano = guardar_en_disco(archivo, destino)

        with conectar() as conexion:
            resultado = conexion.execute(
                """
                INSERT INTO documentos
                    (titulo, nombre_archivo, nombre_guardado, categoria,
                     descripcion, numero_oficio, departamento,
                     fecha_documento, autor, tamano_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datos["titulo"],
                    nombre_original,
                    nombre_guardado,
                    datos["categoria"],
                    datos["descripcion"],
                    datos["numero_oficio"],
                    datos["departamento"],
                    datos["fecha_documento"] or None,
                    datos["autor"],
                    tamano,
                ),
            )
            nuevo_id = resultado.lastrowid
    except ArchivoInvalido as error:
        descartar_generado("documento", destino.name)
        return fallo_subida(request, error.codigo, datos["titulo"], nombre_original)
    except Exception:
        # Si algo falló después de guardar el archivo, no dejamos huérfanos en storage/
        descartar_generado("documento", destino.name)
        logger.exception("No se pudo guardar el documento")
        return fallo_subida(request, "error", datos["titulo"], nombre_original)

    partes = [nombre_original, datos["categoria"], formatear_tamano(tamano)]
    if datos["numero_oficio"]:
        partes.append(f"oficio {datos['numero_oficio']}")
    if datos["departamento"]:
        partes.append(datos["departamento"])

    registrar(
        request,
        "subir",
        entidad="documento",
        entidad_id=nuevo_id,
        entidad_nombre=datos["titulo"],
        detalle=" · ".join(partes),
    )
    return avisar("subido")


@router.get(
    "/documentos/{documento_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver"))],
)
def ficha_documento(
    request: Request,
    documento_id: int,
    aviso: str | None = None,
):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)

    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT id, titulo, nombre_archivo, nombre_guardado, categoria,
                   descripcion, tamano_bytes, numero_oficio, departamento,
                   autor, fecha_documento,
                   datetime(fecha_subida, 'localtime') AS fecha_subida
            FROM documentos
            WHERE id = ?
              AND eliminado_en IS NULL
            """ + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()

    if documento is None:
        raise HTTPException(
            status_code=404,
            detail="Documento no encontrado.",
        )

    # Si llegas con un aviso (por ejemplo, justo después de editar) no es una consulta nueva
    if aviso is None:
        registrar(
            request,
            "consultar",
            entidad="documento",
            entidad_id=documento["id"],
            entidad_nombre=documento["titulo"],
        )

    extension = Path(documento["nombre_archivo"]).suffix.lower()
    disponible = (STORAGE_DIR / documento["nombre_guardado"]).is_file()

    return templates.TemplateResponse(
        request=request,
        name="ficha.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "biblioteca",
            "documento": documento,
            "tipo_archivo": TIPOS_ARCHIVO.get(extension, "Archivo"),
            "extension": extension,
            "tamano": formatear_tamano(documento["tamano_bytes"]),
            "disponible": disponible,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.get(
    "/documentos/{documento_id}/vista",
    dependencies=[Depends(requiere_permiso("ver"))],
)
def previsualizar_documento(request: Request, documento_id: int):
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)
    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT id, titulo, nombre_archivo, nombre_guardado
            FROM documentos
            WHERE id = ? AND eliminado_en IS NULL""" + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()

    if documento is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")

    ruta_archivo = STORAGE_DIR / documento["nombre_guardado"]
    if not ruta_archivo.is_file():
        raise HTTPException(status_code=404, detail="El archivo no existe en el almacenamiento.")

    extension = Path(documento["nombre_archivo"]).suffix.lower()
    registrar(
        request,
        "previsualizar",
        entidad="documento",
        entidad_id=documento_id,
        entidad_nombre=documento["titulo"],
    )

    tipos_en_linea = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    if extension in tipos_en_linea:
        return FileResponse(
            path=ruta_archivo,
            media_type=tipos_en_linea[extension],
            filename=Path(documento["nombre_archivo"]).name,
            content_disposition_type="inline",
            headers={
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    error = None
    texto = None
    if extension in {".xlsx", ".docx", ".pptx"}:
        try:
            pdf, _ = convertir_office_a_pdf(ruta_archivo)
        except ArchivoNoPrevisualizable as exc:
            logger.warning("No se pudo convertir el documento %s con LibreOffice: %s", documento_id, exc)
            error = str(exc)
        else:
            return FileResponse(
                path=pdf,
                media_type="application/pdf",
                filename=f"{Path(documento['nombre_archivo']).stem}.pdf",
                content_disposition_type="inline",
                headers={
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "private, no-store",
                },
            )

    try:
        if not error and extension == ".txt":
            texto = ruta_archivo.read_text(encoding="utf-8-sig", errors="replace")
    except (ArchivoNoPrevisualizable, OSError) as exc:
        logger.warning("No se pudo previsualizar el documento %s: %s", documento_id, exc)
        error = str(exc) if isinstance(exc, ArchivoNoPrevisualizable) else "No se pudo leer el archivo."

    respuesta = templates.TemplateResponse(
        request=request,
        name="previsualizacion.html",
        context={
            "nombre_archivo": documento["nombre_archivo"],
            "extension": extension,
            "texto": texto,
            "error": error,
        },
    )
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Cache-Control"] = "private, no-store"
    respuesta.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'"
    return respuesta


@router.get(
    "/documentos/{documento_id}/editar",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("editar"))],
)
def pagina_editar(
    request: Request,
    documento_id: int,
    aviso: str | None = None,
):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)

    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT id, titulo, nombre_archivo, categoria, descripcion, version,
                   numero_oficio, departamento, autor, fecha_documento,
                   datetime(fecha_subida, 'localtime') AS fecha_subida
            FROM documentos
            WHERE id = ?
              AND eliminado_en IS NULL
            """ + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()

    if documento is None:
        raise HTTPException(
            status_code=404,
            detail="Documento no encontrado.",
        )

    return templates.TemplateResponse(
        request=request,
        name="editar.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "biblioteca",
            "documento": documento,
            "categorias": CATEGORIAS,
            "departamentos": DEPARTAMENTOS,
            "es_admin": request.state.usuario["rol"] == "admin",
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post(
    "/documentos/{documento_id}/editar",
    dependencies=[Depends(requiere_permiso("editar"))],
)
def editar_documento(
    request: Request,
    documento_id: int,
    titulo: str = Form(...),
    categoria: str = Form(...),
    descripcion: str = Form(""),
    numero_oficio: str = Form(""),
    departamento: str = Form(""),
    fecha_documento: str = Form(""),
    autor: str = Form(""),
    version: int = Form(1),
):
    datos, error = limpiar_metadatos(
        titulo, categoria, descripcion, numero_oficio,
        departamento, fecha_documento, autor,
    )
    if error:
        return avisar_edicion(documento_id, error)

    anterior = None
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)

    try:
        with conectar() as conexion:
            anterior = conexion.execute(
                """
                SELECT titulo, categoria, descripcion, numero_oficio,
                       departamento, fecha_documento, autor, version
                FROM documentos
                WHERE id = ?
                  AND eliminado_en IS NULL
                """ + filtro_area,
                [documento_id, *parametros_area],
            ).fetchone()

            if anterior is not None:
                if anterior["version"] != version:
                    return avisar_edicion(documento_id, "conflicto_edicion")
                if request.state.usuario["rol"] != "admin":
                    # El usuario puede editar metadatos del documento accesible,
                    # pero no reclasificarlo para otro departamento ni hacerlo público.
                    datos["departamento"] = anterior["departamento"]
                resultado = conexion.execute(
                    """
                    UPDATE documentos
                    SET titulo = ?, categoria = ?, descripcion = ?,
                        numero_oficio = ?, departamento = ?,
                        fecha_documento = ?, autor = ?, version = version + 1
                    WHERE id = ? AND version = ?""" + filtro_area,
                    (
                        datos["titulo"],
                        datos["categoria"],
                        datos["descripcion"],
                        datos["numero_oficio"],
                        datos["departamento"],
                        datos["fecha_documento"] or None,
                        datos["autor"],
                        documento_id,
                        version,
                        *parametros_area,
                    ),
                )
                if resultado.rowcount != 1:
                    return avisar_edicion(documento_id, "conflicto_edicion")
    except Exception:
        logger.exception("No se pudo editar el documento %s", documento_id)
        registrar(
            request,
            "editar",
            "fallo",
            entidad="documento",
            entidad_id=documento_id,
            entidad_nombre=datos["titulo"],
            detalle="error al guardar los cambios",
        )
        return avisar_edicion(documento_id, "error")

    if anterior is None:
        raise HTTPException(
            status_code=404,
            detail="Documento no encontrado.",
        )

    cambios = describir_cambios(anterior, datos)
    if cambios:
        registrar(
            request,
            "editar",
            entidad="documento",
            entidad_id=documento_id,
            entidad_nombre=datos["titulo"],
            detalle="; ".join(cambios),
        )

    return avisar_edicion(documento_id, "editado")


@router.get(
    "/documentos/{documento_id}/eliminar",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("papelera"))],
)
def pagina_eliminar(
    request: Request,
    documento_id: int,
    aviso: str | None = None,
):
    # Esta ruta solo MUESTRA la confirmación: no borra nada.
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)

    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT id, titulo, nombre_archivo, categoria, tamano_bytes,
                   datetime(fecha_subida, 'localtime') AS fecha_subida
            FROM documentos
            WHERE id = ?
              AND eliminado_en IS NULL
            """ + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()

    if documento is None:
        raise HTTPException(
            status_code=404,
            detail="Documento no encontrado.",
        )

    return templates.TemplateResponse(
        request=request,
        name="eliminar.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "biblioteca",
            "documento": documento,
            "tamano": formatear_tamano(documento["tamano_bytes"]),
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post(
    "/documentos/{documento_id}/eliminar",
    dependencies=[Depends(requiere_permiso("papelera"))],
)
def eliminar_documento(request: Request, documento_id: int):
    documento = None
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)

    # Enviar a papelera conserva el registro y el archivo para poder restaurarlos.
    try:
        with conectar() as conexion:
            fila = conexion.execute(
                """
                SELECT titulo, nombre_archivo
                FROM documentos
                WHERE id = ? AND eliminado_en IS NULL""" + filtro_area,
                [documento_id, *parametros_area],
            ).fetchone()

            if fila is not None:
                documento = dict(fila)
                conexion.execute(
                    """
                    UPDATE documentos
                    SET eliminado_en = CURRENT_TIMESTAMP, eliminado_por = ?
                    WHERE id = ? AND eliminado_en IS NULL""" + filtro_area,
                    (request.state.usuario["id"], documento_id, *parametros_area),
                )
    except Exception:
        logger.exception("No se pudo eliminar el registro %s", documento_id)
        registrar(
            request,
            "papelera_enviar",
            "fallo",
            entidad="documento",
            entidad_id=documento_id,
            detalle="error al enviar el documento a la papelera",
        )
        return avisar_eliminacion(documento_id, "error_eliminar")

    if documento is None:
        raise HTTPException(
            status_code=404,
            detail="Documento no encontrado.",
        )

    registrar(
        request,
        "papelera_enviar",
        entidad="documento",
        entidad_id=documento_id,
        entidad_nombre=documento["titulo"],
        detalle=f"enviado a papelera · archivo: {documento['nombre_archivo']}",
    )

    return RedirectResponse(url="/?aviso=eliminado", status_code=303)


@router.post(
    "/documentos/papelera",
    dependencies=[Depends(requiere_permiso("papelera"))],
)
def enviar_documentos_papelera(
    request: Request,
    documento_ids: list[int] = Form(default=[]),
):
    ids, placeholders, error = leer_seleccion(documento_ids)
    if error:
        return RedirectResponse(url=f"/?aviso={error}", status_code=303)

    filtro_area, parametros_area = filtro_area_documento(request.state.usuario, "d.")
    # La lectura usa el alias ``d``; el UPDATE no. Necesita el filtro sin alias.
    filtro_area_actualizacion, parametros_area_actualizacion = filtro_area_documento(
        request.state.usuario
    )
    try:
        with conectar() as conexion:
            documentos = conexion.execute(
                "SELECT d.id, d.titulo, d.nombre_archivo FROM documentos d "
                f"WHERE d.id IN ({placeholders}) AND d.eliminado_en IS NULL" + filtro_area,
                [*ids, *parametros_area],
            ).fetchall()
            if len(documentos) != len(ids):
                raise HTTPException(status_code=404, detail="Uno o más documentos no están disponibles.")
            conexion.execute(
                "UPDATE documentos SET eliminado_en = CURRENT_TIMESTAMP, eliminado_por = ? "
                f"WHERE id IN ({placeholders}) AND eliminado_en IS NULL" + filtro_area_actualizacion,
                [request.state.usuario["id"], *ids, *parametros_area_actualizacion],
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("No se pudieron enviar documentos seleccionados a la papelera")
        return RedirectResponse(url="/?aviso=error_papelera", status_code=303)

    for documento in documentos:
        registrar(
            request,
            "papelera_enviar",
            entidad="documento",
            entidad_id=documento["id"],
            entidad_nombre=documento["titulo"],
            detalle=f"enviado a papelera en lote · archivo: {documento['nombre_archivo']}",
        )
    return RedirectResponse(url="/?aviso=documentos_papelera", status_code=303)


@router.get(
    "/documentos/{documento_id}/descargar",
    dependencies=[Depends(requiere_permiso("descargar"))],
)
def descargar_documento(request: Request, documento_id: int):
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)
    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT titulo, nombre_archivo, nombre_guardado
            FROM documentos
            WHERE id = ? AND eliminado_en IS NULL""" + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()

    if documento is None:
        raise HTTPException(
            status_code=404,
            detail="Documento no encontrado.",
        )

    ruta_archivo = STORAGE_DIR / documento["nombre_guardado"]

    if not ruta_archivo.is_file():
        registrar(
            request,
            "descargar",
            "fallo",
            entidad="documento",
            entidad_id=documento_id,
            entidad_nombre=documento["titulo"],
            detalle="el archivo no existe en el almacenamiento",
        )
        raise HTTPException(
            status_code=404,
            detail="El archivo no existe en el almacenamiento.",
        )

    registrar(
        request,
        "descargar",
        entidad="documento",
        entidad_id=documento_id,
        entidad_nombre=documento["titulo"],
        detalle=documento["nombre_archivo"],
    )

    return FileResponse(
        path=ruta_archivo,
        filename=documento["nombre_archivo"],
        content_disposition_type="attachment",
    )

