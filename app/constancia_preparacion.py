"""Constancia independiente: sin autorización de recuperación ni lectura de rutas.

La publicación no garantiza durabilidad del directorio ante un apagado en
Windows. El consumidor futuro debe verificar el conjunto bajo bloqueo y tratar
esta constancia como evidencia de integridad, no de autenticidad.
"""
import json
import os
import re
import secrets
import stat
from pathlib import Path

from app.inventario_restauracion import json_estricto

MAX_BYTES = 65536
_HASH = re.compile(r'^[0-9a-f]{64}$')
_OPERACION = re.compile(r'^operacion-[a-z0-9_]{8}$')


def validar(datos):
    campos = {'version', 'operacion', 'inventario_sha256', 'sqlite_anterior',
              'sqlite_verificada', 'sqlite_transformada', 'tareas_suspendidas',
              'clave', 'listo_recuperacion'}
    if not isinstance(datos, dict) or set(datos) not in (campos, campos | {'componentes'}):
        raise ValueError('Constancia incompleta o desconocida')
    if 'componentes' in datos:
        d = datos['componentes']
        if (not isinstance(d, dict) or set(d) != {'sha256', 'bytes', 'entradas'}
                or not isinstance(d['sha256'], str) or not _HASH.fullmatch(d['sha256'])
                or any(type(d[k]) is not int or d[k] <= 0 for k in ('bytes', 'entradas'))):
            raise ValueError('Descriptor de componentes inválido')
    if type(datos['version']) is not int or datos['version'] != 1:
        raise ValueError('Versión desconocida')
    if not isinstance(datos['operacion'], str) or not _OPERACION.fullmatch(datos['operacion']):
        raise ValueError('Operación inválida')
    if not isinstance(datos['inventario_sha256'], str) or not _HASH.fullmatch(datos['inventario_sha256']):
        raise ValueError('Inventario inválido')
    for campo in ('sqlite_anterior', 'sqlite_verificada', 'sqlite_transformada'):
        fila = datos[campo]
        if (not isinstance(fila, dict) or set(fila) != {'sha256', 'tamano'}
                or not isinstance(fila['sha256'], str) or not _HASH.fullmatch(fila['sha256'])
                or type(fila['tamano']) is not int or fila['tamano'] < 0):
            raise ValueError('Descripción SQLite inválida')
    if datos['sqlite_anterior'] != datos['sqlite_verificada']:
        raise ValueError('Las copias anteriores no coinciden')
    if type(datos['tareas_suspendidas']) is not int or datos['tareas_suspendidas'] < 0:
        raise ValueError('Cantidad inválida')
    if datos['clave'] not in ('archivo identificado', 'entorno no acreditado', 'evidencia insuficiente', 'configuracion incompatible'):
        raise ValueError('Estado de clave inválido')
    if datos['listo_recuperacion'] is not False:
        raise ValueError('La constancia no autoriza recuperación')
    return datos


def leer(directorio):
    path = Path(directorio) / 'constancia-preparacion.json'
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or info.st_size > MAX_BYTES:
        raise ValueError('Constancia no regular o excesiva')
    with path.open('rb') as f:
        antes = os.fstat(f.fileno())
        contenido = f.read(MAX_BYTES + 1)
        despues = os.fstat(f.fileno())
    if (len(contenido) > MAX_BYTES or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) !=
            (antes.st_dev, antes.st_ino, antes.st_size, antes.st_mtime_ns) or
            (antes.st_dev, antes.st_ino, antes.st_size, antes.st_mtime_ns) !=
            (despues.st_dev, despues.st_ino, despues.st_size, despues.st_mtime_ns)):
        raise ValueError('Constancia modificada durante lectura')
    return validar(json_estricto(contenido.decode('utf-8')))


def publicar(directorio, datos):
    """Publica sin reemplazo; el llamador debe mantener el bloqueo exclusivo."""
    validar(datos)
    directorio = Path(directorio)
    info = directorio.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Directorio no permitido')
    contenido = json.dumps(datos, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    if len(contenido) > MAX_BYTES:
        raise ValueError('Constancia demasiado grande')
    temporal = directorio / ('.constancia-' + secrets.token_hex(16) + '.tmp')
    final = directorio / 'constancia-preparacion.json'
    creada = False
    try:
        with temporal.open('xb') as archivo:
            creada = True
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        # NTFS, mismo volumen: no sustituye una constancia previa.
        os.link(temporal, final)
        if leer(directorio) != datos:
            raise ValueError('Constancia publicada incoherente')
    finally:
        if creada:
            temporal.unlink()
