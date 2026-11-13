"""Preparación persistente y comprobación administrativa; nunca restaura datos."""
import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing

from app import constancia_preparacion as cp
from app import inventario_restauracion as inv
from app import preparacion_cola as cola
from app import registro_restauracion as r
from app import seleccion_originales as sel
from app.temporal_privado import verificar_acl_privada


def _nombre(op):
    # El identificador proviene exclusivamente del registro v2 validado.
    return '.siged-preparacion-' + op


def _arbol(root, esperadas, presupuesto):
    resultado = {}
    for nombre in ('base', 'storage', 'clave', 'base-candidata'):
        for fila in inv.recorrer(root / nombre, nombre, presupuesto):
            ruta = fila.pop('ruta')
            if ruta in resultado:
                raise ValueError('Componente duplicado')
            resultado[ruta] = fila
    if set(resultado) != set(esperadas) | {'base-candidata'}:
        raise ValueError('Componentes ausentes o adicionales')
    for ruta, fuente in esperadas.items():
        copia = resultado[ruta]
        if fuente['tipo'] != copia['tipo']:
            raise ValueError('Tipo de componente diferente')
        if fuente['tipo'] == 'archivo' and (fuente['sha256'], fuente['tamano']) != (copia['sha256'], copia['tamano']):
            raise ValueError('Componente diferente del inventario')
    if resultado['base-candidata']['tipo'] != 'archivo':
        raise ValueError('Falta SQLite transformada')
    return resultado


def _escribir_manifiesto(root, filas, presupuesto):
    digest = hashlib.sha256()
    total = 0
    with (root / 'componentes.jsonl').open('xb') as f:
        for ruta in sorted(filas):
            linea = (json.dumps({'ruta': ruta, **filas[ruta]}, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
            if len(linea) > 65536:
                raise ValueError('Entrada excesiva')
            presupuesto.comprobar(len(linea), entrada=True)
            f.write(linea)
            digest.update(linea)
            total += len(linea)
        f.flush()
        os.fsync(f.fileno())
    return {'sha256': digest.hexdigest(), 'bytes': total, 'entradas': len(filas)}


def _leer_manifiesto(root, descriptor, esperadas, presupuesto):
    path = root / 'componentes.jsonl'
    info = inv.inspeccionar(path)
    if info is None or not stat.S_ISREG(info.st_mode) or info.st_size != descriptor['bytes']:
        raise ValueError('Manifiesto ausente o diferente')
    digest = hashlib.sha256()
    filas = {}
    with path.open('rb') as f:
        while linea := f.readline(65537):
            presupuesto.comprobar(len(linea), entrada=True)
            if len(linea) > 65536 or not linea.endswith(b'\n'):
                raise ValueError('Manifiesto truncado')
            digest.update(linea)
            fila = inv.json_estricto(linea)
            if not isinstance(fila, dict) or not isinstance(fila.get('ruta'), str):
                raise TypeError('Entrada inválida')
            ruta = fila.pop('ruta')
            if ruta not in esperadas and ruta != 'base-candidata' or ruta in filas:
                raise ValueError('Ruta no autorizada')
            filas[ruta] = fila
    if digest.hexdigest() != descriptor['sha256'] or len(filas) != descriptor['entradas']:
        raise ValueError('Manifiesto contradictorio')
    return filas


def _comprobar_sqlite(root, presupuesto, tareas_suspendidas):
    anterior = None
    transformada = None
    for nombre in ('base', 'base-candidata'):
        path = root / nombre
        cola._comprobar_auxiliares(path)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.set_progress_handler(lambda: cola._interrumpir(presupuesto), 1000)
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('SQLite inválida')
            if nombre == 'base':
                anterior = cola._resumen(db, presupuesto, True)
            else:
                transformada = cola._resumen(db, presupuesto)
        cola._comprobar_auxiliares(path)
    if (anterior[0] != transformada[0] or anterior[1] != transformada[1]
            or anterior[2] != tareas_suspendidas or transformada[2] != 0):
        raise ValueError('Transformación de cola contradictoria')


def publicar(root, evidencia, preparacion, presupuesto):
    esperadas = evidencia['entradas']
    filas = _arbol(root, esperadas, presupuesto)
    _comprobar_sqlite(root, presupuesto, preparacion['tareas_suspendidas'])
    antes = filas['base']
    despues = filas['base-candidata']
    if (antes['sha256'], despues['sha256']) != (preparacion['sha256_antes'], preparacion['sha256_despues']):
        raise ValueError('Huellas SQLite contradictorias')
    descriptor = _escribir_manifiesto(root, filas, presupuesto)
    verificar_acl_privada(root, inv.limite('GESTOR_INVENTARIO_MAX_SEGUNDOS', 3600), presupuesto.max_entradas)
    with os.scandir(root) as entradas:
        raiz = set()
        for entrada in entradas:
            presupuesto.comprobar(entrada=True)
            raiz.add(entrada.name)
    permitido = {'base', 'storage', 'base-candidata', 'componentes.jsonl'}
    if esperadas['clave']['tipo'] != 'ausente': permitido.add('clave')
    if raiz != permitido:
        raise ValueError('Archivos adicionales en preparación')
    base = {'sha256': antes['sha256'], 'tamano': antes['tamano']}
    clave = {'entorno histórico no verificable': 'entorno no acreditado',
             'archivo histórico identificado; autenticidad no comprobada': 'archivo identificado',
             'configuración actual incompatible con procedencia local': 'configuracion incompatible'}.get(preparacion['clave'], 'evidencia insuficiente')
    datos = {'version': 1, 'operacion': evidencia['registro']['operacion'],
             'inventario_sha256': evidencia['registro']['inventario']['sha256'],
             'sqlite_anterior': base, 'sqlite_verificada': base,
             'sqlite_transformada': {'sha256': despues['sha256'], 'tamano': despues['tamano']},
             'tareas_suspendidas': preparacion['tareas_suspendidas'], 'clave': clave,
             'listo_recuperacion': False, 'componentes': descriptor}
    cp.publicar(root, datos)
    return datos


def _verificar_preparado(evidencia):
    """Comprueba las copias contra evidencia v2 ya validada, sin decidir ubicación original."""
    op = evidencia['registro']['operacion']
    root = r.DATA_DIR / _nombre(op)
    info = inv.inspeccionar(root)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise ValueError('Preparación ausente')
    datos = cp.leer(root)
    if datos['operacion'] != op or datos['inventario_sha256'] != evidencia['registro']['inventario']['sha256'] or 'componentes' not in datos:
        raise ValueError('Constancia contradictoria')
    presupuesto = inv.Presupuesto()
    verificar_acl_privada(root, inv.limite('GESTOR_INVENTARIO_MAX_SEGUNDOS', 3600), presupuesto.max_entradas)
    with os.scandir(root) as entradas:
        raiz = set()
        for entrada in entradas:
            presupuesto.comprobar(entrada=True)
            raiz.add(entrada.name)
    permitido = {'base', 'storage', 'base-candidata', 'componentes.jsonl', 'constancia-preparacion.json'}
    if evidencia['entradas']['clave']['tipo'] != 'ausente': permitido.add('clave')
    if raiz != permitido: raise ValueError('Componentes inesperados')
    manifestadas = _leer_manifiesto(root, datos['componentes'], evidencia['entradas'], presupuesto)
    reales = _arbol(root, evidencia['entradas'], presupuesto)
    if reales != manifestadas: raise ValueError('Componente alterado')
    base, candidata = reales['base'], reales['base-candidata']
    if datos['sqlite_verificada'] != {'sha256': base['sha256'], 'tamano': base['tamano']} or datos['sqlite_transformada'] != {'sha256': candidata['sha256'], 'tamano': candidata['tamano']}:
        raise ValueError('Huellas inconsistentes')
    _comprobar_sqlite(root, presupuesto, datos['tareas_suspendidas'])
    origen = evidencia['registro']['clave_origen']
    if (origen == 'entorno' and datos['clave'] != 'entorno no acreditado') or (origen == 'archivo' and datos['clave'] not in ('archivo identificado', 'configuracion incompatible')):
        raise ValueError('Procedencia de clave contradictoria')
    return datos


def _inspeccionar():
    resultado = {'estado': 'no verificable', 'listo_recuperacion': False}
    try:
        evidencia = {}
        if sel._seleccionar(evidencia)['estado'] != 'candidato identificado':
            return resultado
        op = evidencia['registro']['operacion']
        root = r.DATA_DIR / _nombre(op)
        info = inv.inspeccionar(root)
        if info is None:
            resultado['estado'] = 'incompleta'
            return resultado
        if not stat.S_ISDIR(info.st_mode): raise ValueError('Directorio inválido')
        if inv.inspeccionar(root / 'constancia-preparacion.json') is None:
            resultado['estado'] = 'incompleta'
            return resultado
        _verificar_preparado(evidencia)
        final = {}
        if sel._seleccionar(final)['estado'] != 'candidato identificado' or final != evidencia:
            raise ValueError('Evidencia anterior cambió')
        actual = cola.evaluar_clave(evidencia, bool(os.environ.get('GESTOR_SECRET_KEY')))
        resultado.update(estado='preparación íntegra', clave=actual)
    except (OSError, sqlite3.Error, RecursionError, KeyboardInterrupt):
        resultado['estado'] = 'no verificable'
    except (ValueError, TypeError, KeyError):
        resultado['estado'] = 'contradictoria'
    return resultado


def main():
    import argparse

    from app.coordinacion import inspeccionar_preparacion, preparar_persistente
    parser = argparse.ArgumentParser(description='Preparación y diagnóstico sin autorización de recuperación')
    parser.add_argument('operacion', choices=('preparar', 'inspeccionar'), nargs='?', default='inspeccionar')
    opcion = parser.parse_args().operacion
    resultado = preparar_persistente() if opcion == 'preparar' else inspeccionar_preparacion()
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == '__main__':
    main()
