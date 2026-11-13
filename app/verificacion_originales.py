"""Copias efímeras de verificación; nunca restauran ni generan constancias.

Entrada: python -m app.verificacion_originales (SIGED detenido).
GESTOR_VERIFICACION_MAX_BYTES limita las copias (10 GiB por defecto),
GESTOR_VERIFICACION_MARGEN_BYTES reserva 64 MiB libres. Se reutilizan los
presupuestos GESTOR_INVENTARIO_* y GESTOR_SELECCION_MAX_BYTES. El plazo es
cooperativo: no puede cancelar una llamada al sistema bloqueada. Una caída
abrupta puede dejar el directorio temporal, pero nunca autoriza recuperación.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import stat
from contextlib import closing

from app import inventario_restauracion as inv
from app import registro_restauracion as r
from app import seleccion_originales as sel
from app.temporal_privado import directorio_privado


def _verificar(preparar=False, persistente=False):
    salida = {'estado': 'verificación incompleta', 'listo_recuperacion': False}
    try:
        presupuesto = inv.Presupuesto()
        evidencia = {}
        candidato = sel._seleccionar(evidencia)
        salida['seleccion'] = candidato['estado']
        salida['clave_efectiva'] = candidato.get('clave_efectiva', 'sin verificar')
        if candidato['estado'] != 'candidato identificado':
            return salida
        entradas = evidencia['entradas']
        total = sum(f.get('tamano', 0) for f in entradas.values())
        if total > inv.limite('GESTOR_VERIFICACION_MAX_BYTES', 10 * 1024**3):
            raise ValueError('Presupuesto excedido')
        margen = inv.limite('GESTOR_VERIFICACION_MARGEN_BYTES', 64 * 1024**2)
        extra = entradas.get('base', {}).get('tamano', 0) if preparar else 0
        if total + extra > inv.limite('GESTOR_VERIFICACION_MAX_BYTES', 10 * 1024**3):
            raise ValueError('Presupuesto excedido')
        if shutil.disk_usage(r.DATA_DIR).free < total + extra + margen:
            raise ValueError('Espacio insuficiente')
        if persistente and not preparar:
            raise ValueError('La preparación persistente requiere transformación')
        nombre = None
        if persistente:
            from app.preparacion_persistente import _nombre
            nombre = _nombre(evidencia['registro']['operacion'])
        with directorio_privado(r.DATA_DIR, nombre=nombre, conservar=persistente) as temporal:
            from pathlib import Path
            destino = Path(temporal)
            for ruta, fila in entradas.items():
                presupuesto.comprobar(entrada=True)
                partes = ruta.split('/')
                origen = evidencia['raices'][partes[0]]
                for parte in partes[1:]:
                    info = inv.inspeccionar(origen)
                    if info is None or not stat.S_ISDIR(info.st_mode):
                        raise ValueError('Padre de origen inválido')
                    origen = origen / parte
                copia = destino.joinpath(*partes)
                if fila['tipo'] == 'ausente':
                    continue
                antes = inv.inspeccionar(origen)
                if antes is None or inv.identidad(antes) != fila['identidad']:
                    raise ValueError('Identidad de origen cambió')
                if fila['tipo'] == 'directorio':
                    copia.mkdir()
                    continue
                digest = hashlib.sha256(); cantidad = 0
                with origen.open('rb') as fuente, copia.open('xb') as archivo:
                    if inv.identidad(os.fstat(fuente.fileno())) != fila['identidad']:
                        raise ValueError('Origen sustituido')
                    for bloque in iter(lambda: fuente.read(1024**2), b''):
                        presupuesto.comprobar()
                        cantidad += len(bloque)
                        if cantidad > fila['tamano']:
                            raise ValueError('Origen creció')
                        digest.update(bloque); archivo.write(bloque)
                    archivo.flush(); os.fsync(archivo.fileno())
                if cantidad != fila['tamano'] or digest.hexdigest() != fila['sha256']:
                    raise ValueError('Contenido distinto del inventario')
                for path in (origen, copia):
                    huella = inv.huella(path, presupuesto)
                    if (huella['tamano'], huella['sha256']) != (fila['tamano'], fila['sha256']):
                        raise ValueError('Copia o fuente alterada')
                    if path == origen and huella['identidad'] != fila['identidad']:
                        raise ValueError('Identidad cambió')
            db = destino / 'base'
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro&immutable=1', uri=True)) as conexion:
                conexion.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,
                                  inv.limite('GESTOR_VERIFICACION_MAX_CELDA', 16 * 1024**2))
                conexion.set_progress_handler(lambda: _interrumpir(presupuesto), 1000)
                conexion.execute('PRAGMA query_only=ON')
                conexion.execute('PRAGMA trusted_schema=OFF')
                conexion.execute('PRAGMA cache_size=-2048')
                if conexion.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise ValueError('SQLite corrupta')
                if conexion.execute('PRAGMA foreign_key_check').fetchone() is not None:
                    raise ValueError('Relaciones inválidas')
                # Relaciones de expedientes incluso si una base dañada perdió sus FK.
                tablas = {x[0] for x in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if (
                    'expediente_documentos' in tablas
                    and conexion.execute(
                        'SELECT 1 FROM expediente_documentos e LEFT JOIN documentos d ON d.id=e.documento_id '
                        'LEFT JOIN expedientes x ON x.id=e.expediente_id '
                        'WHERE d.id IS NULL OR x.id IS NULL LIMIT 1'
                    ).fetchone()
                ):
                    raise ValueError('Expediente inconsistente')
                # Mismas referencias físicas de respaldo._referencias_archivos,
                # recorridas en flujo sobre esta conexión acotada, incluida papelera.
                referenciados = set()
                for tabla, columna, prefijo in (('documentos', 'nombre_guardado', ''), ('avisos', 'imagen_guardada', 'avisos/'), ('usuarios', 'foto_perfil', 'perfiles/')):
                    if tabla not in tablas:
                        if tabla == 'documentos': raise ValueError('Falta tabla documentos')
                        continue
                    columnas = {x[1] for x in conexion.execute('PRAGMA table_info(' + tabla + ')')}
                    if columna not in columnas:
                        raise ValueError('Esquema incompleto')
                    tamano = 'tamano_bytes' if tabla == 'documentos' and 'tamano_bytes' in columnas else 'NULL'
                    for nombre, size in conexion.execute(f'SELECT {columna}, {tamano} FROM {tabla}'):
                        presupuesto.comprobar(entrada=True)
                        if tabla != 'documentos' and not nombre: continue
                        if not isinstance(nombre, str) or not nombre or nombre in ('.', '..') or '/' in nombre or '\\' in nombre:
                            raise ValueError('Referencia inválida')
                        fila = entradas.get('storage/' + prefijo + nombre)
                        if not fila or fila['tipo'] != 'archivo' or (size is not None and size != fila['tamano']):
                            raise ValueError('Referencia física inválida')
                        referenciados.add('storage/' + prefijo + nombre)
                # Pueden existir archivos históricos o tareas pendientes. Se informan,
                # sin eliminarlos ni interpretar su presencia como autorización.
                salida['archivos_inventariados_sin_referencia'] = sum(
                    ruta.startswith('storage/') and fila['tipo'] == 'archivo' and ruta not in referenciados
                    for ruta, fila in entradas.items())
            if preparar:
                from app.preparacion_cola import evaluar_clave, transformar_copia
                preparacion = transformar_copia(db, destino / 'base-candidata', presupuesto)
                preparacion['operacion'] = evidencia['registro']['operacion']
                preparacion['inventario_sha256'] = evidencia['registro']['inventario']['sha256']
                preparacion['clave'] = evaluar_clave(evidencia, bool(os.environ.get('GESTOR_SECRET_KEY')))
            # Revalida conjunto completo, auxiliares, constancias y origen; sin otro bloqueo.
            final = {}
            if sel._seleccionar(final)['estado'] != 'candidato identificado' or final != evidencia:
                raise ValueError('Evidencia final cambió')
            presupuesto.comprobar()
            if persistente:
                from app.preparacion_persistente import _inspeccionar, publicar
                publicar(destino, evidencia, preparacion, presupuesto)
                comprobacion = _inspeccionar()
                if comprobacion['estado'] != 'preparación íntegra':
                    raise ValueError('Preparación publicada no verificable')
        salida['estado'] = 'preparación íntegra' if persistente else 'copia verificada'
        if preparar:
            salida['preparacion' if persistente else 'preparacion_temporal'] = preparacion
    except (OSError, ValueError, sqlite3.Error, KeyboardInterrupt, RecursionError):
        salida['motivo'] = 'Verificación incompleta: error de copia, integridad, recursos o evidencia.'
    return salida


def _interrumpir(presupuesto):
    try:
        presupuesto.comprobar()
        return 0
    except ValueError:
        return 1


def main():
    from app.coordinacion import verificar_originales_aislados
    print(json.dumps(verificar_originales_aislados(), ensure_ascii=False))


if __name__ == '__main__':
    main()

