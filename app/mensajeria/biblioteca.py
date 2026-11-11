"""Referencias internas a originales de Biblioteca con autorización vigente."""

import os
import sqlite3
import stat
import time
from contextlib import ExitStack, contextmanager
from pathlib import PureWindowsPath
from urllib.parse import quote

from app.acceso_documentos import filtro_area_documento
from app.configuracion import STORAGE_DIR
from app.coordinacion import BloqueoDatos
from app.inventario_restauracion import identidad, inspeccionar
from app.mensajeria import disco, formatos, motor
from app.seguridad import PERMISOS
from app.tipos_archivo import EXTENSIONES_PERMITIDAS

NO_DISPONIBLE = "documento_no_disponible"


@contextmanager
def _sin_detalles():
    try:
        yield
    except motor.ErrorMotor:
        raise
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        raise motor.ErrorMotor(NO_DISPONIBLE) from None


def _alcance(principal, participantes):
    """Aplica los mismos permisos y el filtro de área que las rutas documentales."""
    puede_descargar = True
    filtros = []
    parametros = []
    for participante in participantes:
        usuario = principal.execute(
            "SELECT rol, departamento FROM usuarios WHERE mensajeria_ref=? AND activo=1", (participante,),
        ).fetchone()
        permisos = PERMISOS.get(usuario["rol"], ()) if usuario is not None else ()
        if "ver" not in permisos:
            raise motor.ErrorMotor(NO_DISPONIBLE)
        filtro, area = filtro_area_documento(dict(usuario))
        filtros.append(filtro)
        parametros.extend(area)
        puede_descargar &= "descargar" in permisos
    return "".join(filtros), parametros, puede_descargar


def _consultar(principal, referencia, participantes):
    alcance, parametros, puede_descargar = _alcance(principal, participantes)
    documento = principal.execute(
        "SELECT nombre_archivo, nombre_guardado, mensajeria_original, tamano_bytes, version "
        "FROM documentos WHERE mensajeria_ref=? AND eliminado_en IS NULL" + alcance,
        (referencia, *parametros),
    ).fetchone()
    if documento is None:
        raise motor.ErrorMotor(NO_DISPONIBLE)
    nombre = documento["nombre_guardado"]
    original = documento["nombre_archivo"]
    if (nombre != documento["mensajeria_original"] or not isinstance(nombre, str)
            or not formatos._segmento(nombre) or not isinstance(original, str)
            or len(original) > 260 or not formatos._segmento(original)):
        raise motor.ErrorMotor(NO_DISPONIBLE)
    return documento, puede_descargar


def _identidad_abierta(ruta, archivo, tamano):
    info = inspeccionar(ruta)
    abierto = os.fstat(archivo.fileno())
    if (info is None or not stat.S_ISREG(info.st_mode) or not info.st_ino
            or info.st_nlink != 1 or info.st_size != tamano or abierto.st_size != tamano
            or identidad(info) != identidad(abierto)):
        raise motor.ErrorMotor(NO_DISPONIBLE)
    return identidad(info)


def _abrir_original(pila, documento):
    raiz = pila.enter_context(disco.directorio_fijado(STORAGE_DIR))
    ruta = raiz / documento["nombre_guardado"]
    archivo, _ = disco.abrir(ruta)
    pila.enter_context(archivo)
    return ruta, archivo, _identidad_abierta(ruta, archivo, documento["tamano_bytes"])


def confirmar(remitente, destinatario, texto, clave, adjunto):
    pareja, huella = motor._datos_envio(remitente, destinatario, texto, clave, adjunto)
    if adjunto.tipo != "documento":
        raise motor.ErrorMotor("adjunto_invalido")
    with _sin_detalles(), ExitStack() as pila, motor._transaccion(*pareja) as (principal, db, gen, ahora, dia):
        previa = motor._repeticion(db, remitente, clave, huella)
        if previa is not None:
            return previa
        documento, puede_descargar = _consultar(principal, adjunto.referencia, pareja)
        if adjunto.modalidad == "visualizar_y_descargar" and not puede_descargar:
            raise motor.ErrorMotor(NO_DISPONIBLE)
        # Solo metadatos y apertura NTFS bajo SQLite. El HANDLE queda vivo hasta
        # después del COMMIT y no permite que se sustituya el original.
        _abrir_original(pila, documento)
        solicitud = motor.VerificacionAdjunto(adjunto, remitente, destinatario, gen, clave)
        mensaje = motor._persistir(principal, db, solicitud, pareja, clave, huella, texto, ahora, dia)
        db.execute("INSERT INTO referencias_biblioteca VALUES (?, ?)", (mensaje, adjunto.modalidad))
        return mensaje


def _estado(principal, db, actor, conversacion, mensaje, ahora):
    fila = db.execute(
        """SELECT m.documento_ref, m.remitente_ref, m.destinatario_ref, m.vence_utc, b.modalidad
           FROM mensajes m JOIN referencias_biblioteca b ON b.mensaje_id=m.id
           WHERE m.id=? AND m.conversacion_id=? AND m.tipo_adjunto='documento'
           AND ? IN (m.remitente_ref,m.destinatario_ref) AND m.vence_utc>?
           AND m.vence_utc<=m.confirmado_utc+?""",
        (mensaje, conversacion, actor, ahora, motor.VIGENCIA_DOCUMENTO),
    ).fetchone()
    if fila is None:
        raise motor.ErrorMotor(NO_DISPONIBLE)
    referencia, remitente, destinatario, _vence, modalidad = fila
    documento, descarga = _consultar(principal, referencia, (remitente, destinatario))
    acciones = ("visualizar", "descargar") if descarga and modalidad == "visualizar_y_descargar" else ("visualizar",)
    return fila, documento, acciones


def _formato(archivo, documento):
    extension = PureWindowsPath(documento["nombre_guardado"]).suffix.lower()
    if extension not in EXTENSIONES_PERMITIDAS or extension != PureWindowsPath(documento["nombre_archivo"]).suffix.lower():
        return None
    plazo = time.monotonic() + 30

    def comprobar():
        if time.monotonic() >= plazo:
            raise ValueError("Formato no verificable")

    try:
        formatos.validar(archivo, extension, documento["tamano_bytes"], comprobar)
    except ValueError:
        return None
    finally:
        archivo.seek(0)
    return "jpg" if extension == ".jpeg" else extension[1:]


@contextmanager
def _acceso(actor, conversacion, mensaje, accion=None, *, informar_estado_sesion=False):
    with ExitStack() as pila:
        try:
            motor._referencia(conversacion)
            motor._referencia(mensaje)
            # Impide que una restauración comience con el original aún abierto.
            pila.enter_context(BloqueoDatos(exclusivo=False))
            with motor._transaccion(actor) as (principal, db, generacion, ahora, _):
                estado = _estado(principal, db, actor, conversacion, mensaje, ahora)
            referencia, documento, acciones = estado
            if accion is not None and accion not in acciones:
                raise motor.ErrorMotor(NO_DISPONIBLE)
            ruta, archivo, fisica = _abrir_original(pila, documento)
            formato = None if accion == "descargar" else _formato(archivo, documento)
            if formato is None and accion == "visualizar":
                raise motor.ErrorMotor(NO_DISPONIBLE)
            with motor._transaccion(actor) as (principal, db, actual, ahora, _):
                if (generacion != actual or estado != _estado(principal, db, actor, conversacion, mensaje, ahora)
                        or fisica != _identidad_abierta(ruta, archivo, documento["tamano_bytes"])):
                    raise motor.ErrorMotor(NO_DISPONIBLE)
        except motor.ErrorMotor as error:
            if informar_estado_sesion and str(error) in {"sesion_no_valida", "identidad_no_reconciliada"}:
                raise
            raise motor.ErrorMotor(NO_DISPONIBLE) from None
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            raise motor.ErrorMotor(NO_DISPONIBLE) from None
        yield archivo, {
            "origen": "biblioteca", "estado": "disponible", "nombre_original": documento["nombre_archivo"],
            "formato": formato, "vence_utc": referencia["vence_utc"], "tamano_bytes": documento["tamano_bytes"],
            "acciones": [a for a in acciones if formato is not None or a == "descargar"],
        }


def tarjeta(actor, conversacion, mensaje, *, informar_estado_sesion=False):
    """Proyección autorizada para un mensaje. Su contenido no debe cachearse."""
    try:
        with _acceso(actor, conversacion, mensaje, informar_estado_sesion=informar_estado_sesion) as (_, metadatos):
            return metadatos
    except motor.ErrorMotor as error:
        if str(error) != NO_DISPONIBLE:
            raise
        return {"estado": "no_disponible"}


@contextmanager
def abrir_visualizacion(actor, conversacion, mensaje, *, informar_estado_sesion=False):
    """Entrega el original fijado y sus acciones autorizadas."""
    with _acceso(actor, conversacion, mensaje, "visualizar", informar_estado_sesion=informar_estado_sesion) as resultado:
        yield resultado


@contextmanager
def abrir_descarga(actor, conversacion, mensaje, *, informar_estado_sesion=False):
    with _acceso(actor, conversacion, mensaje, "descargar",
                 informar_estado_sesion=informar_estado_sesion) as (archivo, metadatos):
        nombre = quote(metadatos["nombre_original"], safe="")
        yield archivo, {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f"attachment; filename*=UTF-8''{nombre}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        }
