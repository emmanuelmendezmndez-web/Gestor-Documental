"""Ensayo transaccional efímero: no publica una fuente de recuperación."""
import hashlib
import json
import os
import sqlite3
from contextlib import closing

from app import inventario_restauracion as inv
from app.mensajeria.identidad_documental import verificar_disparadores_para_recuperacion

_MENSAJE = 'Tarea suspendida al restaurar; requiere revisión'
_ESTADOS = {'pendiente', 'suspendida', 'completada', 'cancelada'}


def _comprobar_auxiliares(base):
    for sufijo in ('-wal', '-shm', '-journal'):
        if inv.inspeccionar(base.with_name(base.name + sufijo)) is not None:
            raise ValueError('Auxiliar SQLite inesperado')


def evaluar_clave(evidencia, entorno_actual):
    origen = evidencia['registro']['clave_origen']
    fila = evidencia['entradas'].get('clave', {})
    if origen == 'entorno':
        return 'entorno histórico no verificable'
    if origen != 'archivo' or fila.get('tipo') != 'archivo':
        return 'evidencia insuficiente'
    if entorno_actual:
        return 'configuración actual incompatible con procedencia local'
    return 'archivo histórico identificado; autenticidad no comprobada'


def _resumen(conexion, presupuesto, transformar=False):
    h = hashlib.sha256()
    pendientes = total = 0
    for fila in conexion.execute('SELECT id,tipo,nombre,identidad,estado,intentos,ultimo_error,creado_en FROM eliminaciones_pendientes ORDER BY id'):
        presupuesto.comprobar(entrada=True)
        valores = list(fila)
        if valores[4] not in _ESTADOS:
            raise ValueError('Estado de cola desconocido')
        total += 1
        if valores[4] == 'pendiente':
            pendientes += 1
            if transformar:
                valores[4], valores[6] = 'suspendida', _MENSAJE
        h.update(json.dumps(valores, ensure_ascii=True, separators=(',', ':')).encode('utf-8') + b'\n')
    return h.digest(), total, pendientes


def transformar_copia(anterior, candidata, presupuesto):
    _comprobar_auxiliares(anterior)
    _comprobar_auxiliares(candidata)
    antes = inv.huella(anterior, presupuesto)
    with anterior.open('rb') as origen, candidata.open('xb') as destino:
        for bloque in iter(lambda: origen.read(1024 * 1024), b''):
            presupuesto.comprobar()
            destino.write(bloque)
        destino.flush()
        os.fsync(destino.fileno())
    copia = inv.huella(candidata, presupuesto)
    if (copia['tamano'], copia['sha256']) != (antes['tamano'], antes['sha256']):
        raise ValueError('Copia diferente')
    with closing(sqlite3.connect(candidata)) as conexion:
        conexion.set_progress_handler(lambda: _interrumpir(presupuesto), 1000)
        conexion.execute('PRAGMA trusted_schema=OFF')
        conexion.execute('BEGIN IMMEDIATE')
        try:
            verificar_disparadores_para_recuperacion(conexion)
            esperado, total, pendientes = _resumen(conexion, presupuesto, True)
            cambio = conexion.execute("UPDATE eliminaciones_pendientes SET estado='suspendida', ultimo_error=? WHERE estado='pendiente'", (_MENSAJE,))
            if cambio.rowcount != pendientes:
                raise ValueError('Cantidad incoherente')
            actual, total_final, pendientes_final = _resumen(conexion, presupuesto)
            if actual != esperado or total != total_final or pendientes_final:
                raise ValueError('Cola incoherente')
            if conexion.execute('PRAGMA integrity_check').fetchone() != ('ok',) or conexion.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Base inválida')
            conexion.commit()
        except BaseException:
            conexion.rollback()
            raise
    _comprobar_auxiliares(anterior)
    _comprobar_auxiliares(candidata)
    despues = inv.huella(candidata, presupuesto)
    if inv.huella(anterior, presupuesto) != antes:
        raise ValueError('Copia anterior cambió')
    return {'sha256_antes': antes['sha256'], 'sha256_despues': despues['sha256'],
            'tareas_suspendidas': pendientes, 'total_tareas': total,
            'estado': 'ensayo temporal; no autoriza recuperación'}


def _interrumpir(presupuesto):
    try:
        presupuesto.comprobar()
        return 0
    except ValueError:
        return 1


def main():
    from app.coordinacion import preparar_cola_aislada
    print(json.dumps(preparar_cola_aislada(), ensure_ascii=False))


if __name__ == '__main__':
    main()
