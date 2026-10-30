import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from math import ceil
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.acceso_documentos import condicion_area_documento, filtro_area_documento
from app.actividad import registrar
from app.archivos import ArchivoInvalido, TAMANO_BLOQUE, TAMANO_MAXIMO, guardar_en_disco
from app.asistente import router as router_asistente
from app.catalogos import CATEGORIAS, DEPARTAMENTOS
from app.database import conectar, inicializar_db, normalizar_texto
from app.ediciones import CAMPOS_COMPARABLES, describir_cambios
from app.metadatos import limpiar_metadatos
from app.mensajes import AVISOS, MENSAJES_HTTP, MOTIVOS_SUBIDA
from app.ordenes_biblioteca import EXPR_EXTENSION, EXPR_FECHA, ORDENES, ORDEN_PREDETERMINADO
from app.plantillas import templates
from app.previsualizacion import (
    ArchivoNoPrevisualizable,
    convertir_office_a_pdf,
)
from app.respuestas_documentos import avisar, avisar_edicion, avisar_eliminacion
from app.seleccion import leer_seleccion
from app.servicios.papelera import purgar_documentos_papelera
from app.servicios.inicio import buscar_global_datos, dashboard_datos
from app.servicios.avisos import crear_aviso_servicio
from app.rutas_actividad import router as router_actividad
from app.rutas_cuenta import router as router_cuenta
from app.rutas_usuarios import router as router_usuarios
from app.tipos_archivo import EXTENSIONES_PERMITIDAS, TIPOS_ARCHIVO
from app.utilidades import escapar_like, fecha_valida, formatear_espacio_disco, formatear_tamano
from app.seguridad import (
    NoAutenticado,
    autenticar,
    buscar_usuario,
    demasiados_intentos,
    limpiar_fallos,
    obtener_clave_secreta,
    registrar_fallo,
    requiere_permiso,
    usuario_actual,
    verificar_password,
)

logger = logging.getLogger("gestor")

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
DATA_DIR = Path(os.environ.get("GESTOR_DATA_DIR", str(BASE_DIR))).expanduser().resolve()
STORAGE_DIR = DATA_DIR / "storage"  # separado del código y fuera de app/static
AVISOS_DIR = STORAGE_DIR / "avisos"


POR_PAGINA = 20  # documentos por página en la biblioteca
COOKIE_HTTPS_ONLY = os.environ.get("GESTOR_HTTPS_ONLY", "").strip().lower() in {
    "1", "true", "yes", "si"
}



@asynccontextmanager
async def lifespan(app: FastAPI):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    AVISOS_DIR.mkdir(parents=True, exist_ok=True)
    inicializar_db()

    with conectar() as conexion:
        hay_usuarios = conexion.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
    if hay_usuarios is None:
        logger.warning(
            "No hay usuarios registrados. Crea el primero con: python -m app.crear_usuario"
        )

    yield


app = FastAPI(title="Gestor Documental", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=obtener_clave_secreta(),
    session_cookie="gestor_sesion",
    max_age=10 * 60 * 60,  # la sesión dura 10 horas desde la última actividad
    same_site="lax",
    https_only=COOKIE_HTTPS_ONLY,  # activa GESTOR_HTTPS_ONLY detrás de HTTPS
)

app.mount(
    "/static",
    StaticFiles(directory=APP_DIR / "static"),
    name="static",
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        APP_DIR / "static" / "img" / "siged-isotipo.png",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )

app.include_router(router_usuarios)
app.include_router(router_actividad)
app.include_router(router_cuenta)
app.include_router(router_asistente)


# ---------- Errores ----------

@app.exception_handler(NoAutenticado)
async def manejar_no_autenticado(request: Request, exc: NoAutenticado):
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def manejar_error_http(request: Request, exc: StarletteHTTPException):
    titulo_error, detalle = MENSAJES_HTTP.get(
        exc.status_code, ("Error", "Ocurrió un problema al procesar la solicitud.")
    )
    # Respetamos los textos propios en español; los genéricos en inglés se reemplazan
    if isinstance(exc.detail, str) and exc.detail not in (
        "Not Found",
        "Forbidden",
        "Method Not Allowed",
    ):
        detalle = exc.detail

    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=exc.status_code,
        context={
            "titulo": "Gestor Documental",
            "pagina": "",
            "codigo": exc.status_code,
            "titulo_error": titulo_error,
            "detalle": detalle,
        },
    )


# ---------- Funciones de apoyo ----------

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




# ---------- Inicio y cierre de sesión ----------

@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request, aviso: str | None = None):
    if usuario_actual(request):
        return RedirectResponse(url="/inicio", status_code=303)

    tipo, mensaje = AVISOS.get(aviso, (None, None))

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "login",
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@app.post("/login")
def iniciar_sesion(
    request: Request,
    usuario: str = Form(...),
    password: str = Form(...),
):
    usuario = usuario.strip()
    ip = request.client.host if request.client else "desconocida"
    clave = f"{usuario.lower()[:100]}|{ip}"

    # Mientras dure el bloqueo no se anota cada intento, para que el registro no se llene
    if demasiados_intentos(clave):
        return RedirectResponse(url="/login?aviso=bloqueado", status_code=303)

    fila = None
    if len(usuario) <= 100 and len(password) <= 200:
        fila = autenticar(usuario, password)

    if fila is None:
        registrar_fallo(clave)

        # Solo se guarda el nombre si corresponde a un usuario real: así no queda
        # en el registro una contraseña que alguien tecleó por error en este campo.
        existente = buscar_usuario(usuario) if len(usuario) <= 100 else None
        if existente is None:
            motivo = "usuario no registrado"
        elif not existente["activo"]:
            motivo = "cuenta desactivada"
        else:
            motivo = "contraseña incorrecta"
        if demasiados_intentos(clave):
            motivo += " (cuenta bloqueada temporalmente)"

        registrar(request, "inicio_sesion", "fallo", usuario=existente, detalle=motivo)
        return RedirectResponse(url="/login?aviso=credenciales", status_code=303)

    limpiar_fallos(clave)
    request.session.clear()  # sesión nueva en cada inicio
    request.session["usuario_id"] = fila["id"]
    request.session["version"] = fila["version_sesion"]
    request.session["saludo_clippy_pendiente"] = True

    registrar(
        request,
        "inicio_sesion",
        usuario={"id": fila["id"], "usuario": fila["usuario"]},
    )
    return RedirectResponse(url="/inicio", status_code=303)


@app.post("/salir")
def cerrar_sesion(request: Request):
    usuario = usuario_actual(request)
    if usuario:
        registrar(request, "cierre_sesion", usuario=usuario)

    request.session.clear()
    return RedirectResponse(url="/login?aviso=sesion_cerrada", status_code=303)


# ---------- Inicio / Dashboard ----------

@app.get(
    "/buscar",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver"))],
)
def buscar_global(request: Request, q: str = ""):
    return templates.TemplateResponse(request=request, name="buscar.html",
                                      context=buscar_global_datos(request.state.usuario, q))


@app.get(
    "/inicio",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver"))],
)
def dashboard(request: Request):
    contexto = dashboard_datos(request.state.usuario, STORAGE_DIR)
    contexto["saludo_clippy_entrada"] = bool(request.session.pop("saludo_clippy_pendiente", False))
    return templates.TemplateResponse(request=request, name="inicio.html", context=contexto)


# ---------- Gestión de avisos (solo administradores) ----------

@app.get(
    "/avisos",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("avisos"))],
)
def gestionar_avisos(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    with conectar() as conexion:
        avisos = conexion.execute(
            """
            SELECT a.id, a.titulo, a.cuerpo, a.imagen_guardada,
                   a.imagen_nombre, a.departamento, a.publicado,
                   datetime(a.fecha_creacion, 'localtime') AS fecha_creacion,
                   COALESCE(u.nombre, u.usuario, 'Administrador') AS autor
            FROM avisos a
            LEFT JOIN usuarios u ON u.id = a.autor_id
            ORDER BY a.fecha_creacion DESC, a.id DESC
            """
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="avisos_admin.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "inicio",
            "avisos": avisos,
            "departamentos": DEPARTAMENTOS,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@app.post("/avisos", dependencies=[Depends(requiere_permiso("avisos"))])
def crear_aviso(
    request: Request, titulo: str = Form(...), cuerpo: str = Form(""),
    departamento: str = Form(""), publicado: int = Form(1),
    imagen: UploadFile | None = File(None),
):
    codigo = crear_aviso_servicio(request, titulo, cuerpo, departamento, publicado, imagen, AVISOS_DIR)
    return RedirectResponse(url=f"/avisos?aviso={codigo}", status_code=303)


@app.post(
    "/avisos/{aviso_id}/estado",
    dependencies=[Depends(requiere_permiso("avisos"))],
)
def cambiar_estado_aviso(
    request: Request,
    aviso_id: int,
    publicado: int = Form(...),
):
    if publicado not in (0, 1):
        raise HTTPException(status_code=400, detail="Estado de aviso no válido.")
    with conectar() as conexion:
        aviso = conexion.execute(
            "SELECT titulo FROM avisos WHERE id = ?",
            (aviso_id,),
        ).fetchone()
        if aviso is None:
            raise HTTPException(status_code=404, detail="Aviso no encontrado.")
        conexion.execute("UPDATE avisos SET publicado = ? WHERE id = ?", (publicado, aviso_id))

    registrar(
        request,
        "aviso_estado",
        entidad="aviso",
        entidad_id=aviso_id,
        entidad_nombre=aviso["titulo"],
        detalle="publicado" if publicado else "oculto",
    )
    return RedirectResponse(url="/avisos?aviso=aviso_estado", status_code=303)


@app.post(
    "/avisos/{aviso_id}/eliminar",
    dependencies=[Depends(requiere_permiso("avisos"))],
)
def eliminar_aviso(request: Request, aviso_id: int):
    with conectar() as conexion:
        aviso = conexion.execute(
            "SELECT titulo, imagen_guardada FROM avisos WHERE id = ?",
            (aviso_id,),
        ).fetchone()
        if aviso is None:
            raise HTTPException(status_code=404, detail="Aviso no encontrado.")
        conexion.execute("DELETE FROM avisos WHERE id = ?", (aviso_id,))

    if aviso["imagen_guardada"]:
        try:
            (AVISOS_DIR / aviso["imagen_guardada"]).unlink(missing_ok=True)
        except OSError:
            logger.exception("No se pudo borrar la imagen del aviso %s", aviso_id)
    registrar(
        request,
        "aviso_eliminar",
        entidad="aviso",
        entidad_id=aviso_id,
        entidad_nombre=aviso["titulo"],
    )
    return RedirectResponse(url="/avisos?aviso=aviso_eliminado", status_code=303)


@app.get(
    "/avisos/{aviso_id}/imagen",
    dependencies=[Depends(requiere_permiso("ver"))],
)
def imagen_aviso(request: Request, aviso_id: int):
    with conectar() as conexion:
        aviso = conexion.execute(
            "SELECT imagen_guardada, imagen_nombre, departamento, publicado FROM avisos WHERE id = ?",
            (aviso_id,),
        ).fetchone()

    if aviso is None or not aviso["imagen_guardada"]:
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")
    usuario = request.state.usuario
    es_admin = usuario["rol"] == "admin"
    visible = aviso["publicado"] and (
        not aviso["departamento"]
        or aviso["departamento"] == usuario.get("departamento", "")
    )
    if not es_admin and not visible:
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")

    extension = Path(aviso["imagen_guardada"]).suffix.lower()
    tipos_imagen = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    if extension not in tipos_imagen:
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")
    ruta_imagen = AVISOS_DIR / aviso["imagen_guardada"]
    if not ruta_imagen.is_file():
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")
    return FileResponse(
        path=ruta_imagen,
        media_type=tipos_imagen[extension],
        filename=aviso["imagen_nombre"] or ruta_imagen.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


# ---------- Biblioteca ----------

@app.get(
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

    # Los elementos enviados a la papelera no aparecen en la biblioteca.
    condiciones = ["eliminado_en IS NULL"]
    parametros = []
    condicion_area, parametros_area = condicion_area_documento(request.state.usuario)
    if condicion_area:
        condiciones.append(condicion_area)
        parametros.extend(parametros_area)

    # Búsqueda general: cada palabra debe aparecer en el título, el archivo o la
    # descripción, sin importar mayúsculas ni acentos.
    for palabra in normalizar_texto(filtros["buscar"]).split()[:8]:
        termino = f"%{escapar_like(palabra)}%"
        condiciones.append(
            "(normalizar(titulo) LIKE ? ESCAPE '\\' "
            "OR normalizar(nombre_archivo) LIKE ? ESCAPE '\\' "
            "OR normalizar(descripcion) LIKE ? ESCAPE '\\')"
        )
        parametros.extend([termino, termino, termino])

    if filtros["categoria"]:
        condiciones.append("categoria = ?")
        parametros.append(filtros["categoria"])

    if filtros["oficio"]:
        condiciones.append("normalizar(numero_oficio) LIKE ? ESCAPE '\\'")
        parametros.append(f"%{escapar_like(normalizar_texto(filtros['oficio']))}%")

    if filtros["departamento"]:
        condiciones.append("departamento = ?")
        parametros.append(filtros["departamento"])

    if filtros["autor"]:
        condiciones.append("normalizar(autor) LIKE ? ESCAPE '\\'")
        parametros.append(f"%{escapar_like(normalizar_texto(filtros['autor']))}%")

    if filtros["desde"]:
        condiciones.append(f"{EXPR_FECHA} >= ?")
        parametros.append(filtros["desde"])

    if filtros["hasta"]:
        condiciones.append(f"{EXPR_FECHA} <= ?")
        parametros.append(filtros["hasta"])

    # "donde" y "orden_sql" solo unen textos fijos escritos arriba;
    # los valores que escribe el usuario van siempre en "parametros".
    donde = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""
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


# ---------- Expedientes ----------

@app.get(
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


@app.post(
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


@app.get(
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


@app.post(
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


@app.get(
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


@app.post(
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


@app.post(
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


# ---------- Subir ----------

@app.get(
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


@app.post("/subir", dependencies=[Depends(requiere_permiso("subir"))])
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
        destino.unlink(missing_ok=True)
        return fallo_subida(request, error.codigo, datos["titulo"], nombre_original)
    except Exception:
        # Si algo falló después de guardar el archivo, no dejamos huérfanos en storage/
        destino.unlink(missing_ok=True)
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


# ---------- Ficha ----------

@app.get(
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


@app.get(
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


# ---------- Editar ----------

@app.get(
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


@app.post(
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


# ---------- Eliminar ----------

@app.get(
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


@app.post(
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


@app.post(
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


# ---------- Papelera ----------

@app.get(
    "/papelera",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("restaurar"))],
)
def ver_papelera(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario, "d.")
    with conectar() as conexion:
        documentos = conexion.execute(
            """
            SELECT d.id, d.titulo, d.nombre_archivo, d.categoria,
                   d.eliminado_en, u.usuario AS eliminado_por_nombre
            FROM documentos d
            LEFT JOIN usuarios u ON u.id = d.eliminado_por
            WHERE d.eliminado_en IS NOT NULL""" + filtro_area + """
            ORDER BY d.eliminado_en DESC, d.id DESC
            """,
            parametros_area,
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="papelera.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "papelera",
            "documentos": documentos,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@app.post(
    "/documentos/{documento_id}/restaurar",
    dependencies=[Depends(requiere_permiso("restaurar"))],
)
def restaurar_documento(request: Request, documento_id: int):
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)
    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT titulo FROM documentos WHERE id = ? AND eliminado_en IS NOT NULL" + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()
        if fila is None:
            raise HTTPException(status_code=404, detail="Documento no encontrado en la papelera.")
        conexion.execute(
            "UPDATE documentos SET eliminado_en = NULL, eliminado_por = NULL "
            "WHERE id = ? AND eliminado_en IS NOT NULL" + filtro_area,
            (documento_id, *parametros_area),
        )

    registrar(request, "restaurar", entidad="documento", entidad_id=documento_id,
              entidad_nombre=fila["titulo"])
    return RedirectResponse(url="/papelera?aviso=restaurado", status_code=303)


@app.post(
    "/papelera/restaurar",
    dependencies=[Depends(requiere_permiso("restaurar"))],
)
def restaurar_documentos_masivo(
    request: Request,
    documento_ids: list[int] = Form(default=[]),
):
    ids, placeholders, error = leer_seleccion(documento_ids)
    if error:
        return RedirectResponse(url=f"/papelera?aviso={error}", status_code=303)

    filtro_area, parametros_area = filtro_area_documento(request.state.usuario, "d.")
    # El SELECT usa el alias ``d`` y el UPDATE no; filtrar cada consulta
    # con su referencia correcta evita que SQLite rechace la restauración.
    filtro_area_actualizacion, parametros_area_actualizacion = filtro_area_documento(
        request.state.usuario
    )
    with conectar() as conexion:
        documentos = conexion.execute(
            "SELECT d.id, d.titulo FROM documentos d "
            f"WHERE d.id IN ({placeholders}) AND d.eliminado_en IS NOT NULL" + filtro_area,
            [*ids, *parametros_area],
        ).fetchall()
        if len(documentos) != len(ids):
            raise HTTPException(status_code=404, detail="Uno o más documentos no están disponibles en tu papelera.")
        conexion.execute(
            "UPDATE documentos SET eliminado_en = NULL, eliminado_por = NULL "
            f"WHERE id IN ({placeholders}) AND eliminado_en IS NOT NULL" + filtro_area_actualizacion,
            [*ids, *parametros_area_actualizacion],
        )

    for documento in documentos:
        registrar(
            request,
            "restaurar",
            entidad="documento",
            entidad_id=documento["id"],
            entidad_nombre=documento["titulo"],
            detalle="restauración en lote",
        )
    return RedirectResponse(url="/papelera?aviso=documentos_restaurados", status_code=303)


@app.post(
    "/papelera/eliminar-seleccionados",
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def eliminar_documentos_seleccionados(request: Request, documento_ids: list[int] = Form(default=[])):
    ids, _, error = leer_seleccion(documento_ids)
    if error:
        return RedirectResponse(url=f"/papelera?aviso={error}", status_code=303)
    try:
        purgar_documentos_papelera(request, STORAGE_DIR, ids)
    except HTTPException:
        raise
    except Exception:
        logger.exception("No se pudieron eliminar los documentos seleccionados de la papelera")
        return RedirectResponse(url="/papelera?aviso=error_papelera", status_code=303)
    return RedirectResponse(url="/papelera?aviso=documentos_purgados", status_code=303)


@app.post(
    "/papelera/vaciar",
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def vaciar_papelera(request: Request, password: str = Form(...)):
    if request.state.usuario["rol"] != "admin":
        return RedirectResponse(url="/papelera?aviso=clave_incorrecta", status_code=303)
    ip = request.client.host if request.client else "desconocida"
    clave = f"vaciar_papelera|{request.state.usuario['id']}|{ip}"
    if demasiados_intentos(clave):
        return RedirectResponse(url="/papelera?aviso=bloqueado", status_code=303)
    with conectar() as conexion:
        usuario = conexion.execute(
            "SELECT password_hash FROM usuarios WHERE id = ? AND activo = 1",
            (request.state.usuario["id"],),
        ).fetchone()
    if usuario is None or not password or len(password) > 200 or not verificar_password(password, usuario["password_hash"]):
        registrar_fallo(clave)
        return RedirectResponse(url="/papelera?aviso=clave_incorrecta", status_code=303)
    limpiar_fallos(clave)
    try:
        purgar_documentos_papelera(request, STORAGE_DIR)
    except Exception:
        logger.exception("No se pudo vaciar la papelera")
        return RedirectResponse(url="/papelera?aviso=error_papelera", status_code=303)
    return RedirectResponse(url="/papelera?aviso=papelera_vacia", status_code=303)


@app.post(
    "/documentos/{documento_id}/eliminar-definitivamente",
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def eliminar_definitivamente(request: Request, documento_id: int):
    purgar_documentos_papelera(request, STORAGE_DIR, [documento_id], individual=True)
    return RedirectResponse(url="/papelera?aviso=eliminado_definitivo", status_code=303)


# ---------- Descargar ----------

@app.get(
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
