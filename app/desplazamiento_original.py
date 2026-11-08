"""Desplazamiento conservador de originales inventariados; no instala datos.

Solo para Windows, bajo bloqueo exclusivo. Los registros son evidencia de
integridad, no de autenticidad. El arranque permanece bloqueado por v2.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess

from app import inventario_restauracion as inv
from app import preparacion_persistente as pp
from app import preparacion_cola as cola
from app import registro_restauracion as r
from app import seleccion_originales as sel
from app.temporal_privado import directorio_privado, verificar_acl_raiz_conservacion

_COMPONENTES = ('base', 'storage', 'clave')
_MAX = 65536


def _iguales(a, b):
    # Igualdad JSON estricta: evita que True sea aceptado como el entero 1.
    return json.dumps(a, ensure_ascii=True, sort_keys=True, separators=(',', ':')) == json.dumps(b, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def _nombre(op):
    return '.siged-conservacion-' + op


def _leer(path):
    info = inv.inspeccionar(path)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX:
        raise ValueError('Registro no regular o excesivo')
    with path.open('rb') as archivo:
        antes = os.fstat(archivo.fileno())
        contenido = archivo.read(_MAX + 1)
        despues = os.fstat(archivo.fileno())
    actual = inv.inspeccionar(path)
    if (len(contenido) > _MAX or len(contenido) != info.st_size or actual is None
            or inv.identidad(info) != inv.identidad(antes) or inv.identidad(info) != inv.identidad(despues)
            or inv.identidad(info) != inv.identidad(actual)):
        raise ValueError('Registro cambió durante lectura')
    return inv.json_estricto(contenido.decode('utf-8'))


def _publicar(path, datos):
    contenido = json.dumps(datos, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    if len(contenido) > _MAX:
        raise ValueError('Registro excesivo')
    existente = _leer(path)
    if existente is not None:
        if not _iguales(existente, datos):
            raise ValueError('Registro anterior contradictorio')
        return
    temporal = path.parent / ('.registro-' + secrets.token_hex(16) + '.tmp')
    with temporal.open('xb') as archivo:
        archivo.write(contenido)
        archivo.flush()
        os.fsync(archivo.fileno())
    # Publicación sin sustitución. Una caída puede dejar el temporal como evidencia.
    os.link(temporal, path)
    if not _iguales(_leer(path), datos):
        raise ValueError('No se pudo verificar la publicación')
    temporal.unlink()


def _evidencia_registro(operacion):
    presupuesto = inv.Presupuesto()
    principal = r.leer(r.REGISTRO)
    if not principal or principal['version'] != 2 or principal['estado'] == 'finalizada' or principal['operacion'] != operacion:
        raise ValueError('Registro pendiente no coincide')
    raiz = inv.inspeccionar(r.RAIZ)
    op = r.RAIZ / operacion
    info = inv.inspeccionar(op)
    if raiz is None or not stat.S_ISDIR(raiz.st_mode) or info is None or not stat.S_ISDIR(info.st_mode):
        raise ValueError('Operación no disponible')
    inicio = r.leer(op / 'inicio.json')
    if (not inicio or inicio['estado'] != 'iniciada' or inicio['version'] != 2
            or r.invariantes(inicio) != r.invariantes(principal)
            or r.leer(op / 'finalizada.json') is not None or r.leer(op / 'finalizada-v1.json') is not None):
        raise ValueError('Evidencia inicial contradictoria')
    # No permitir que otra operación incompleta quede oculta por esta selección.
    with os.scandir(r.RAIZ) as entradas:
        for entrada in entradas:
            presupuesto.comprobar(entrada=True)
            if entrada.name == operacion:
                continue
            if not re.fullmatch(r'operacion-[a-z0-9_]{8}', entrada.name):
                raise ValueError('Evidencia histórica desconocida')
            otra = r.RAIZ / entrada.name
            info_otra = inv.inspeccionar(otra)
            if info_otra is None or not stat.S_ISDIR(info_otra.st_mode):
                raise ValueError('Operación histórica no verificable')
            previo, final, legado = (r.leer(otra / n) for n in ('inicio.json', 'finalizada.json', 'finalizada-v1.json'))
            if previo:
                if (previo['version'] != 2 or previo['estado'] != 'iniciada' or previo['operacion'] != entrada.name
                        or not final or final['estado'] != 'finalizada' or r.invariantes(previo) != r.invariantes(final) or legado):
                    raise ValueError('Operación histórica incierta')
                inv.verificar(otra, previo['inventario'], presupuesto)
            elif (not legado or legado['version'] != 1 or legado['estado'] != 'finalizada'
                  or legado['operacion'] != entrada.name or final or inv.inspeccionar(otra / 'inventario.jsonl')):
                raise ValueError('Operación histórica incierta')
    for base in (sel.DB_PATH, op / 'anterior-base', r.DATA_DIR / _nombre(operacion) / 'base'):
        cola._comprobar_auxiliares(base)
    inv.verificar(op, principal['inventario'], presupuesto)
    esperado = {}
    digest = hashlib.sha256()
    with (op / 'inventario.jsonl').open('rb') as fuente:
        while linea := fuente.readline(_MAX + 1):
            if len(linea) > _MAX or not linea.endswith(b'\n'):
                raise ValueError('Inventario truncado')
            presupuesto.comprobar(len(linea), entrada=True)
            digest.update(linea)
            fila = inv.json_estricto(linea)
            inv.validar_fila(fila)
            if fila['conjunto'] == 'anterior':
                esperado[fila['ruta']] = {k: v for k, v in fila.items() if k not in ('conjunto', 'ruta')}
    if digest.hexdigest() != principal['inventario']['sha256']:
        raise ValueError('Inventario cambiado')
    evidencia = {'registro': principal, 'entradas': esperado}
    pp._verificar_preparado(evidencia)
    return evidencia


def _verificar_arbol(path, nombre, esperadas):
    presupuesto = inv.Presupuesto()
    max_bytes = inv.limite('GESTOR_SELECCION_MAX_BYTES', 10 * 1024**3)
    esperados = {k: v for k, v in esperadas.items() if k == nombre or k.startswith(nombre + '/')}
    if sum(v.get('tamano', 0) for v in esperados.values()) > max_bytes:
        raise ValueError('Límite de lectura excedido')
    vistos = {}
    for fila in inv.recorrer(path, nombre, presupuesto):
        presupuesto.comprobar(entrada=True)
        ruta = fila.pop('ruta')
        if ruta in vistos:
            raise ValueError('Entrada duplicada')
        vistos[ruta] = fila
    if vistos != esperados:
        raise ValueError('Identidad o contenido del original no coincide')


def _cargar_plan(root, evidencia):
    plan = _leer(root / 'intenciones.json')
    if not isinstance(plan, dict) or set(plan) != {'version', 'registro', 'origenes', 'componentes'} or type(plan['version']) is not int or plan['version'] != 1:
        raise ValueError('Intenciones incompletas')
    if not _iguales(plan['registro'], evidencia['registro']):
        raise ValueError('Operación o secuencia contradictoria')
    origenes, componentes = plan['origenes'], plan['componentes']
    if not isinstance(origenes, dict) or set(origenes) != set(_COMPONENTES) or not isinstance(componentes, dict) or set(componentes) != set(_COMPONENTES):
        raise ValueError('Componentes del plan inválidos')
    for nombre in _COMPONENTES:
        esperado = evidencia['entradas'][nombre]
        if not _iguales(componentes[nombre], esperado):
            raise ValueError('Identidad o huella contradictoria')
        ubicacion = origenes[nombre]
        if esperado['tipo'] == 'ausente':
            if ubicacion != 'originalmente ausente': raise ValueError('Ausencia contradictoria')
        else:
            if ubicacion not in ('activo', 'guardado'): raise ValueError('Origen no autorizado')
            if nombre in ('base', 'storage') or evidencia['registro']['clave_origen'] == 'archivo':
                paso = r.CAMBIOS.index(nombre + '-guardar')
                sec = evidencia['registro']['secuencia']
                if (ubicacion == 'guardado' and sec < 2 * paso + 1) or (ubicacion == 'activo' and sec > 2 * paso + 1):
                    raise ValueError('Origen contradice la secuencia')
    return plan


def _rutas(evidencia, plan, nombre, root):
    activos = {'base': sel.DB_PATH, 'storage': sel.STORAGE_DIR, 'clave': sel.SECRET_PATH}
    origen = activos[nombre] if plan['origenes'][nombre] == 'activo' else r.RAIZ / evidencia['registro']['operacion'] / ('anterior-' + nombre)
    return origen, root / nombre


def _comprobar_estado(root, evidencia, plan):
    estados = {}
    for nombre in _COMPONENTES:
        intencion = _leer(root / ('intencion-' + nombre + '.json'))
        confirmacion = _leer(root / ('confirmacion-' + nombre + '.json'))
        fila = plan['componentes'][nombre]
        if fila['tipo'] == 'ausente':
            if intencion is not None or confirmacion is not None or inv.inspeccionar(root / nombre) is not None:
                raise ValueError('Evidencia de ausencia contradictoria')
            for path in (getattr(sel, {'base': 'DB_PATH', 'storage': 'STORAGE_DIR', 'clave': 'SECRET_PATH'}[nombre]), r.RAIZ / evidencia['registro']['operacion'] / ('anterior-' + nombre)):
                if inv.inspeccionar(path) is not None: raise ValueError('Componente ausente apareció')
            estados[nombre] = 'originalmente ausente'
            continue
        esperado_evento = {'version': 1, 'operacion': evidencia['registro']['operacion'], 'componente': nombre,
                           'origen': plan['origenes'][nombre], 'destino': 'conservacion/' + nombre,
                           'inventario_sha256': evidencia['registro']['inventario']['sha256'], 'evidencia': fila}
        if intencion is not None and not _iguales(intencion, esperado_evento):
            raise ValueError('Intención contradictoria')
        if confirmacion is not None and (intencion is None or not _iguales(confirmacion, esperado_evento)):
            raise ValueError('Confirmación contradictoria')
        origen, destino = _rutas(evidencia, plan, nombre, root)
        activo = getattr(sel, {'base': 'DB_PATH', 'storage': 'STORAGE_DIR', 'clave': 'SECRET_PATH'}[nombre])
        guardado_original = r.RAIZ / evidencia['registro']['operacion'] / ('anterior-' + nombre)
        otra = guardado_original if plan['origenes'][nombre] == 'activo' else activo
        otra_info = inv.inspeccionar(otra)
        if otra_info is not None and inv.identidad(otra_info) == fila['identidad']:
            raise ValueError('Identidad original en ubicación adicional')
        fuente, guardado = inv.inspeccionar(origen), inv.inspeccionar(destino)
        if (fuente is None) == (guardado is None):
            raise ValueError('Origen y destino ambiguos')
        if guardado is not None:
            if intencion is None: raise ValueError('Destino sin intención')
            _verificar_arbol(destino, nombre, evidencia['entradas'])
            estados[nombre] = 'desplazado confirmado' if confirmacion else 'desplazado sin confirmación'
        else:
            if confirmacion is not None: raise ValueError('Confirmación sin desplazamiento')
            _verificar_arbol(origen, nombre, evidencia['entradas'])
            estados[nombre] = 'en origen'
    return estados


def _operar(operacion, confirmar, componente, mover):
    resultado = {'estado': 'no verificable', 'listo_recuperacion': False}
    if (not isinstance(operacion, str) or not re.fullmatch(r'operacion-[a-z0-9_]{8}', operacion)
            or confirmar != operacion or componente not in _COMPONENTES):
        resultado['motivo'] = 'Operación, confirmación o componente inválido.'
        return resultado
    try:
        if os.name != 'nt': raise ValueError('Se requiere Windows')
        root = r.DATA_DIR / _nombre(operacion)
        info = inv.inspeccionar(root)
        if info is None:
            evidencia = {}
            seleccionado = sel._seleccionar(evidencia)
            if seleccionado['estado'] != 'candidato identificado' or evidencia['registro']['operacion'] != operacion:
                raise ValueError('No hay original inequívoco')
            if pp._inspeccionar()['estado'] != 'preparación íntegra':
                raise ValueError('Preparación no verificable')
            if not mover:
                estado = ('originalmente ausente' if seleccionado['componentes'][componente] == 'originalmente ausente' else 'en origen')
                resultado.update(estado=estado, componente=componente)
                return resultado
            with directorio_privado(r.DATA_DIR, nombre=_nombre(operacion), conservar=True) as temporal:
                root = Path(temporal)
                plan = {'version': 1, 'registro': evidencia['registro'], 'origenes': seleccionado['componentes'],
                        'componentes': {n: evidencia['entradas'][n] for n in _COMPONENTES}}
                _publicar(root / 'intenciones.json', plan)
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Conservación no disponible')
        evidencia = _evidencia_registro(operacion)
        presupuesto = inv.Presupuesto()
        verificar_acl_raiz_conservacion(root, inv.limite('GESTOR_INVENTARIO_MAX_SEGUNDOS', 3600), presupuesto.max_entradas)
        plan = _cargar_plan(root, evidencia)
        estados = _comprobar_estado(root, evidencia, plan)
        estado = estados[componente]
        if estado == 'originalmente ausente':
            resultado.update(estado=estado, componente=componente)
            return resultado
        if not mover:
            resultado.update(estado=estado, componente=componente)
            return resultado
        fila = plan['componentes'][componente]
        evento = {'version': 1, 'operacion': operacion, 'componente': componente,
                  'origen': plan['origenes'][componente], 'destino': 'conservacion/' + componente,
                  'inventario_sha256': evidencia['registro']['inventario']['sha256'], 'evidencia': fila}
        if estado == 'en origen':
            _publicar(root / ('intencion-' + componente + '.json'), evento)
            if _comprobar_estado(root, evidencia, plan)[componente] != 'en origen':
                raise ValueError('Origen cambió tras registrar la intención')
            origen, destino = _rutas(evidencia, plan, componente, root)
            # Mismos volúmenes: no se cae en copia+eliminación.
            if origen.lstat().st_dev != root.lstat().st_dev:
                raise ValueError('Movimiento entre volúmenes no autorizado')
            if inv.inspeccionar(destino) is not None:
                raise ValueError('Destino ocupado')
            _verificar_arbol(origen, componente, evidencia['entradas'])
            os.rename(origen, destino)  # Windows rechaza un destino existente.
            _verificar_arbol(destino, componente, evidencia['entradas'])
        _publicar(root / ('confirmacion-' + componente + '.json'), evento)
        finales = _comprobar_estado(root, evidencia, plan)
        if finales[componente] != 'desplazado confirmado':
            raise ValueError('Resultado no confirmado')
        resultado.update(estado='desplazado confirmado', componente=componente)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, MemoryError, KeyboardInterrupt, subprocess.TimeoutExpired):
        resultado['motivo'] = 'Evidencia incompleta o contradictoria; conserve los archivos y revise administrativamente.'
    return resultado


def main():
    from app.coordinacion import desplazar_original, inspeccionar_desplazamiento
    parser = argparse.ArgumentParser(description='Conservación de originales sin habilitar recuperación')
    parser.add_argument('accion', choices=('inspeccionar', 'desplazar'))
    parser.add_argument('--operacion', required=True)
    parser.add_argument('--confirmar-operacion', required=True)
    parser.add_argument('--componente', required=True, choices=_COMPONENTES)
    args = parser.parse_args()
    fn = desplazar_original if args.accion == 'desplazar' else inspeccionar_desplazamiento
    print(json.dumps(fn(args.operacion, args.confirmar_operacion, args.componente), ensure_ascii=False))


if __name__ == '__main__':
    main()
