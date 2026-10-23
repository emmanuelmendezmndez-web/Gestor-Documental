import logging
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

from app.actividad import registrar
from app.database import conectar, inicializar_db, normalizar_texto
from app.plantillas import templates
from app.rutas_actividad import router as router_actividad
from app.rutas_cuenta import router as router_cuenta
from app.rutas_usuarios import router as router_usuarios
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
)

logger = logging.getLogger("gestor")

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
STORAGE_DIR = BASE_DIR / "storage"  # fuera de app/static: los archivos no son públicos

CATEGORIAS = ["Oficios", "Actas", "Informes", "Contratos", "Otros"]

# Departamentos disponibles. Los de abajo son ejemplos: cámbialos por los reales.
DEPARTAMENTOS = [
    "Presidencia Municipal",
    "Secretaría Municipal",
    "Tesorería",
    "Obras Públicas",
    "Desarrollo Social",
    "Recursos Humanos",
    "Seguridad Pública",
    "Servicios Públicos",
    "Otro",
]

EXTENSIONES_PERMITIDAS = {".pdf", ".docx", ".xlsx", ".txt", ".png", ".jpg", ".jpeg"}
TIPOS_ARCHIVO = {
    ".pdf": "Documento PDF",
    ".docx": "Documento de Word",
    ".xlsx": "Hoja de cálculo de Excel",
    ".txt": "Archivo de texto",
    ".png": "Imagen PNG",
    ".jpg": "Imagen JPG",
    ".jpeg": "Imagen JPG",
}
TAMANO_MAXIMO = 20 * 1024 * 1024  # 20 MB
TAMANO_BLOQUE = 1024 * 1024  # se lee de 1 MB en 1 MB
POR_PAGINA = 20  # documentos por página en la biblioteca

# Fecha "efectiva" de un documento: la fecha del oficio y, si no se indicó,
# la fecha en que se registró. Así los documentos antiguos también se ordenan y filtran.
EXPR_FECHA = "COALESCE(NULLIF(fecha_documento, ''), date(fecha_subida, 'localtime'))"

# Extensión del archivo (lo que va después del último punto), para ordenar por tipo
EXPR_EXTENSION = (
    "lower(substr(nombre_archivo, "
    "length(rtrim(nombre_archivo, replace(nombre_archivo, '.', ''))) + 1))"
)

# Ordenamientos disponibles. Lo que llega por la URL solo se usa como clave de este
# diccionario; nunca se inserta directamente en la consulta.
ORDENES = {
    "reciente": ("Recién subidos", "id DESC"),
    "fecha_desc": ("Fecha del documento (más recientes)", f"{EXPR_FECHA} DESC, id DESC"),
    "fecha_asc": ("Fecha del documento (más antiguos)", f"{EXPR_FECHA} ASC, id ASC"),
    "titulo_asc": ("Título (A-Z)", "normalizar(titulo) ASC, id DESC"),
    "titulo_desc": ("Título (Z-A)", "normalizar(titulo) DESC, id DESC"),
    "categoria": ("Categoría", "normalizar(categoria) ASC, normalizar(titulo) ASC"),
    "tipo": ("Tipo de archivo", f"{EXPR_EXTENSION} ASC, normalizar(titulo) ASC"),
}
ORDEN_PREDETERMINADO = "reciente"

# Los avisos se piden por código, así nadie puede inyectar texto en la página desde la URL
AVISOS = {
    "subido": ("exito", "Documento subido correctamente."),
    "editado": ("exito", "Documento actualizado correctamente."),
    "eliminado": ("exito", "Documento eliminado correctamente."),
    "sesion_cerrada": ("exito", "Sesión cerrada correctamente."),
    "campos": ("error", "Revisa los datos: el título es obligatorio (máx. 200 caracteres), la descripción admite hasta 2000, el número de oficio hasta 60 y el autor hasta 100."),
    "categoria": ("error", "La categoría seleccionada no es válida."),
    "departamento": ("error", "El departamento seleccionado no es válido."),
    "fecha": ("error", "La fecha del documento no es válida."),
    "formato": ("error", "Formato no permitido. Usa PDF, DOCX, XLSX, TXT, PNG o JPG."),
    "grande": ("error", "El archivo supera el máximo de 20 MB."),
    "vacio": ("error", "El archivo está vacío."),
    "error": ("error", "Ocurrió un error al guardar el documento. Inténtalo de nuevo."),
    "error_eliminar": ("error", "No se pudo eliminar el documento. Inténtalo de nuevo."),
    "credenciales": ("error", "Usuario o contraseña incorrectos."),
    "bloqueado": ("error", "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo."),
}

# Motivos que se anotan en el registro cuando falla una subida
MOTIVOS_SUBIDA = {
    "campos": "datos inválidos (título, descripción, oficio o autor)",
    "categoria": "categoría no válida",
    "departamento": "departamento no válido",
    "fecha": "fecha del documento no válida",
    "formato": "formato no permitido",
    "grande": "archivo mayor al máximo permitido",
    "vacio": "archivo vacío",
    "error": "error al guardar",
}

# Campos que se comparan para describir una edición en el registro de actividad
CAMPOS_COMPARABLES = [
    ("titulo", "título"),
    ("categoria", "categoría"),
    ("numero_oficio", "n.º de oficio"),
    ("departamento", "departamento"),
    ("fecha_documento", "fecha del documento"),
    ("autor", "autor"),
]

MENSAJES_HTTP = {
    403: ("Acceso denegado", "No tienes permiso para realizar esta acción."),
    404: ("No encontrado", "No se encontró lo que buscas."),
    405: ("Acción no permitida", "Esta dirección no admite esa acción."),
}


class ArchivoInvalido(Exception):
    def __init__(self, codigo: str):
        self.codigo = codigo


@asynccontextmanager
async def lifespan(app: FastAPI):
    STORAGE_DIR.mkdir(exist_ok=True)
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
    max_age=8 * 60 * 60,  # la sesión dura 8 horas desde la última actividad
    same_site="lax",
    https_only=False,  # cámbialo a True cuando uses HTTPS
)

app.mount(
    "/static",
    StaticFiles(directory=APP_DIR / "static"),
    name="static",
)

app.include_router(router_usuarios)
app.include_router(router_actividad)
app.include_router(router_cuenta)


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

def avisar(codigo: str) -> RedirectResponse:
    # Éxito: a la biblioteca para ver el documento. Error: de vuelta al formulario.
    # 303: tras el POST el navegador hace GET, y recargar no reenvía el formulario
    ruta = "/" if codigo == "subido" else "/subir"
    return RedirectResponse(url=f"{ruta}?aviso={codigo}", status_code=303)


def avisar_edicion(documento_id: int, codigo: str) -> RedirectResponse:
    # Éxito: a la ficha del documento. Error: de vuelta al formulario de edición.
    if codigo == "editado":
        ruta = f"/documentos/{documento_id}"
    else:
        ruta = f"/documentos/{documento_id}/editar"
    return RedirectResponse(url=f"{ruta}?aviso={codigo}", status_code=303)


def avisar_eliminacion(documento_id: int, codigo: str) -> RedirectResponse:
    # Éxito: a la biblioteca. Error: de vuelta a la pantalla de confirmación.
    if codigo == "eliminado":
        ruta = "/"
    else:
        ruta = f"/documentos/{documento_id}/eliminar"
    return RedirectResponse(url=f"{ruta}?aviso={codigo}", status_code=303)


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


def limpiar_metadatos(
    titulo: str,
    categoria: str,
    descripcion: str,
    numero_oficio: str,
    departamento: str,
    fecha_documento: str,
    autor: str,
):
    """Limpia y valida los datos que comparten 'subir' y 'editar'.
    Devuelve (datos, None) si todo está bien, o (None, código_de_error)."""
    datos = {
        "titulo": titulo.strip(),
        "categoria": categoria,
        "descripcion": descripcion.strip(),
        "numero_oficio": numero_oficio.strip(),
        "departamento": departamento,
        "fecha_documento": fecha_documento.strip(),
        "autor": autor.strip(),
    }

    if (
        not datos["titulo"]
        or len(datos["titulo"]) > 200
        or len(datos["descripcion"]) > 2000
        or len(datos["numero_oficio"]) > 60
        or len(datos["autor"]) > 100
    ):
        return None, "campos"

    if datos["categoria"] not in CATEGORIAS:
        return None, "categoria"

    # El departamento es opcional, pero si se indica debe estar en la lista
    if datos["departamento"] and datos["departamento"] not in DEPARTAMENTOS:
        return None, "departamento"

    if datos["fecha_documento"]:
        try:
            datos["fecha_documento"] = date.fromisoformat(
                datos["fecha_documento"]
            ).isoformat()
        except ValueError:
            return None, "fecha"

    return datos, None


def describir_cambios(anterior, datos: dict) -> list[str]:
    """Texto de lo que cambió en una edición, para el registro de actividad.
    De la descripción solo se indica que cambió, no su contenido."""
    cambios = []
    for campo, etiqueta in CAMPOS_COMPARABLES:
        antes = anterior[campo] or ""
        despues = datos[campo] or ""
        if antes != despues:
            cambios.append(f"{etiqueta}: «{antes or '—'}» → «{despues or '—'}»")

    if (anterior["descripcion"] or "") != datos["descripcion"]:
        cambios.append("descripción modificada")

    return cambios


def fecha_valida(texto: str) -> str:
    """Devuelve la fecha como AAAA-MM-DD, o una cadena vacía si no es válida."""
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        return ""


def formatear_tamano(total_bytes: int) -> str:
    """Convierte bytes a un texto legible: 512 B, 48.3 KB, 2.3 MB..."""
    tamano = float(total_bytes)
    for unidad in ("B", "KB", "MB", "GB"):
        if tamano < 1024 or unidad == "GB":
            if unidad == "B":
                return f"{int(tamano)} B"
            return f"{tamano:.1f} {unidad}"
        tamano /= 1024


def guardar_en_disco(archivo: UploadFile, destino: Path) -> int:
    """Copia el archivo por bloques, valida el tamaño real y devuelve los bytes escritos."""
    tamano = 0
    with destino.open("wb") as salida:
        while bloque := archivo.file.read(TAMANO_BLOQUE):
            tamano += len(bloque)
            if tamano > TAMANO_MAXIMO:
                raise ArchivoInvalido("grande")
            salida.write(bloque)
    if tamano == 0:
        raise ArchivoInvalido("vacio")
    return tamano


def escapar_like(texto: str) -> str:
    """Evita que % y _ escritos por el usuario se comporten como comodines."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------- Inicio y cierre de sesión ----------

@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request, aviso: str | None = None):
    if usuario_actual(request):
        return RedirectResponse(url="/", status_code=303)

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

    registrar(
        request,
        "inicio_sesion",
        usuario={"id": fila["id"], "usuario": fila["usuario"]},
    )
    return RedirectResponse(url="/", status_code=303)


@app.post("/salir")
def cerrar_sesion(request: Request):
    usuario = usuario_actual(request)
    if usuario:
        registrar(request, "cierre_sesion", usuario=usuario)

    request.session.clear()
    return RedirectResponse(url="/login?aviso=sesion_cerrada", status_code=303)


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

    condiciones = []
    parametros = []

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

    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT id, titulo, nombre_archivo, nombre_guardado, categoria,
                   descripcion, tamano_bytes, numero_oficio, departamento,
                   autor, fecha_documento,
                   datetime(fecha_subida, 'localtime') AS fecha_subida
            FROM documentos
            WHERE id = ?
            """,
            (documento_id,),
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
            "tamano": formatear_tamano(documento["tamano_bytes"]),
            "disponible": disponible,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


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

    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT id, titulo, nombre_archivo, categoria, descripcion,
                   numero_oficio, departamento, autor, fecha_documento,
                   datetime(fecha_subida, 'localtime') AS fecha_subida
            FROM documentos
            WHERE id = ?
            """,
            (documento_id,),
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
):
    datos, error = limpiar_metadatos(
        titulo, categoria, descripcion, numero_oficio,
        departamento, fecha_documento, autor,
    )
    if error:
        return avisar_edicion(documento_id, error)

    anterior = None

    try:
        with conectar() as conexion:
            anterior = conexion.execute(
                """
                SELECT titulo, categoria, descripcion, numero_oficio,
                       departamento, fecha_documento, autor
                FROM documentos
                WHERE id = ?
                """,
                (documento_id,),
            ).fetchone()

            if anterior is not None:
                conexion.execute(
                    """
                    UPDATE documentos
                    SET titulo = ?, categoria = ?, descripcion = ?,
                        numero_oficio = ?, departamento = ?,
                        fecha_documento = ?, autor = ?
                    WHERE id = ?
                    """,
                    (
                        datos["titulo"],
                        datos["categoria"],
                        datos["descripcion"],
                        datos["numero_oficio"],
                        datos["departamento"],
                        datos["fecha_documento"] or None,
                        datos["autor"],
                        documento_id,
                    ),
                )
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
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def pagina_eliminar(
    request: Request,
    documento_id: int,
    aviso: str | None = None,
):
    # Esta ruta solo MUESTRA la confirmación: no borra nada.
    tipo, mensaje = AVISOS.get(aviso, (None, None))

    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT id, titulo, nombre_archivo, categoria, tamano_bytes,
                   datetime(fecha_subida, 'localtime') AS fecha_subida
            FROM documentos
            WHERE id = ?
            """,
            (documento_id,),
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
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def eliminar_documento(request: Request, documento_id: int):
    documento = None

    # 1) Primero el registro: si esto falla, el documento queda intacto.
    try:
        with conectar() as conexion:
            fila = conexion.execute(
                """
                SELECT titulo, nombre_archivo, nombre_guardado
                FROM documentos
                WHERE id = ?
                """,
                (documento_id,),
            ).fetchone()

            if fila is not None:
                documento = dict(fila)
                conexion.execute(
                    "DELETE FROM documentos WHERE id = ?",
                    (documento_id,),
                )
    except Exception:
        logger.exception("No se pudo eliminar el registro %s", documento_id)
        registrar(
            request,
            "eliminar",
            "fallo",
            entidad="documento",
            entidad_id=documento_id,
            detalle="error al eliminar el registro",
        )
        return avisar_eliminacion(documento_id, "error_eliminar")

    if documento is None:
        raise HTTPException(
            status_code=404,
            detail="Documento no encontrado.",
        )

    # 2) Después el archivo. Si no se puede borrar (por ejemplo, está abierto en
    #    otro programa en Windows), el registro ya no existe: solo lo anotamos.
    archivo_borrado = True
    try:
        (STORAGE_DIR / documento["nombre_guardado"]).unlink(missing_ok=True)
    except OSError:
        archivo_borrado = False
        logger.exception(
            "Registro %s eliminado, pero el archivo %s sigue en storage/",
            documento_id,
            documento["nombre_guardado"],
        )

    detalle = f"archivo: {documento['nombre_archivo']}"
    if not archivo_borrado:
        detalle += " (el archivo no se pudo borrar de storage/)"

    registrar(
        request,
        "eliminar",
        entidad="documento",
        entidad_id=documento_id,
        entidad_nombre=documento["titulo"],
        detalle=detalle,
    )

    return avisar_eliminacion(documento_id, "eliminado")


# ---------- Descargar ----------

@app.get(
    "/documentos/{documento_id}/descargar",
    dependencies=[Depends(requiere_permiso("descargar"))],
)
def descargar_documento(request: Request, documento_id: int):
    with conectar() as conexion:
        documento = conexion.execute(
            """
            SELECT titulo, nombre_archivo, nombre_guardado
            FROM documentos
            WHERE id = ?
            """,
            (documento_id,),
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