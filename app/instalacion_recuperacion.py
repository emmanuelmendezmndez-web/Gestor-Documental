"""Instalación administrativa interrumpible; no habilita el arranque.

Las rutas se derivan del registro v2 y los nombres fijos, nunca del JSON. Los
originales y la preparación permanecen conservados. La integridad no autentica.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path

from app import constancia_preparacion as cp
from app import desplazamiento_original as des
from app import inventario_restauracion as inv
from app import preparacion_cola as cola
from app import preparacion_persistente as pp
from app import registro_restauracion as r
from app import seleccion_originales as sel
from app.temporal_privado import verificar_acl_raiz_conservacion

_NOMBRES = ('base', 'storage', 'clave')


def _activos():
    return {'base': sel.DB_PATH, 'storage': sel.STORAGE_DIR, 'clave': sel.SECRET_PATH}


def _recorrer_acotado(path, ruta, presupuesto, bytes_leidos, profundidad=0):
    presupuesto.comprobar(entrada=True)
    if profundidad > 128:
        raise ValueError('Árbol demasiado profundo')
    info = inv.inspeccionar(path)
    if info is None:
        yield {'ruta': ruta, 'tipo': 'ausente'}
    elif stat.S_ISREG(info.st_mode):
        bytes_leidos[0] += info.st_size
        if bytes_leidos[0] > inv.limite('GESTOR_VERIFICACION_MAX_BYTES', 10 * 1024**3):
            raise ValueError('Límite de datos excedido')
        yield {'ruta': ruta, **inv.huella(path, presupuesto)}
    else:
        yield {'ruta': ruta, 'tipo': 'directorio', 'identidad': inv.identidad(info)}
        with os.scandir(path) as hijos:
            for hijo in hijos:
                yield from _recorrer_acotado(Path(hijo.path), ruta + '/' + hijo.name, presupuesto, bytes_leidos, profundidad + 1)
        actual = inv.inspeccionar(path)
        if actual is None or inv.identidad(info) != inv.identidad(actual):
            raise ValueError('Directorio cambió')


def _huella(path, nombre):
    presupuesto = inv.Presupuesto()
    filas = list(_recorrer_acotado(path, nombre, presupuesto, [0]))
    h = hashlib.sha256()
    for fila in sorted(filas, key=lambda x: x['ruta']):
        linea = (json.dumps(fila, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
        presupuesto.comprobar(len(linea))
        h.update(linea)
    return {'sha256': h.hexdigest(), 'entradas': len(filas), 'tipo': filas[0]['tipo'] if len(filas) == 1 else 'directorio'}


def _copiar(src, dst, fila, presupuesto):
    antes = inv.inspeccionar(src)
    if antes is None or not stat.S_ISREG(antes.st_mode):
        raise ValueError('Fuente no disponible')
    digest = hashlib.sha256()
    cantidad = 0
    with src.open('rb') as f, dst.open('xb') as salida:
        if inv.identidad(os.fstat(f.fileno())) != inv.identidad(antes):
            raise ValueError('Identidad de fuente cambió')
        while bloque := f.read(1024 * 1024):
            presupuesto.comprobar()
            cantidad += len(bloque)
            if cantidad > fila['tamano']:
                raise ValueError('Fuente creció')
            digest.update(bloque)
            salida.write(bloque)
        salida.flush()
        os.fsync(salida.fileno())
    if cantidad != fila['tamano'] or digest.hexdigest() != fila['sha256']:
        raise ValueError('Contenido preparado no coincide')
    for path in (src, dst):
        huella = inv.huella(path, presupuesto)
        if (huella['tamano'], huella['sha256']) != (fila['tamano'], fila['sha256']):
            raise ValueError('Copia alterada')
    actual = inv.inspeccionar(src)
    if actual is None or inv.identidad(antes) != inv.identidad(actual):
        raise ValueError('Fuente sustituida')


def _comparar_con_preparacion(path, nombre, evidencia):
    """Compara contenido y árbol con v2 y la constancia, sin confiar en el plan."""
    presupuesto = inv.Presupuesto()
    constancia = cp.leer(r.DATA_DIR / pp._nombre(evidencia['registro']['operacion']))
    if nombre == 'base':
        esperadas = {'base': {'tipo': 'archivo', **constancia['sqlite_transformada']}}
    else:
        esperadas = {k: v for k, v in evidencia['entradas'].items()
                     if k == nombre or k.startswith(nombre + '/')}
    encontrados = {}
    for fila in _recorrer_acotado(path, nombre, presupuesto, [0]):
        ruta = fila.pop('ruta')
        if ruta in encontrados: raise ValueError('Ruta duplicada')
        encontrados[ruta] = fila
    if set(encontrados) != set(esperadas): raise ValueError('Árbol diferente de la preparación')
    for ruta, esperado in esperadas.items():
        real = encontrados[ruta]
        if real['tipo'] != esperado['tipo']:
            raise ValueError('Tipo diferente de la preparación')
        if real['tipo'] == 'archivo' and (real['tamano'], real['sha256']) != (esperado['tamano'], esperado['sha256']):
            raise ValueError('Contenido diferente de la preparación')


def _crear_etapa(root, evidencia):
    pp_root = r.DATA_DIR / pp._nombre(evidencia['registro']['operacion'])
    constancia = cp.leer(pp_root)
    filas = evidencia['entradas']
    total = sum(f.get('tamano', 0) for f in filas.values()) + constancia['sqlite_transformada']['tamano']
    if total > inv.limite('GESTOR_VERIFICACION_MAX_BYTES', 10 * 1024**3):
        raise ValueError('Límite de copia excedido')
    if shutil.disk_usage(root).free < total + inv.limite('GESTOR_VERIFICACION_MARGEN_BYTES', 64 * 1024**2):
        raise ValueError('Espacio insuficiente')
    nombre = 'instalacion-' + secrets.token_hex(16)
    etapa = root / nombre
    etapa.mkdir()
    presupuesto = inv.Presupuesto()
    _copiar(pp_root / 'base-candidata', etapa / 'base', constancia['sqlite_transformada'], presupuesto)
    clave = filas['clave']
    if clave['tipo'] != 'archivo': raise ValueError('Clave local ausente')
    _copiar(pp_root / 'clave', etapa / 'clave', clave, presupuesto)
    for ruta in sorted((x for x in filas if x == 'storage' or x.startswith('storage/')), key=lambda x: (x.count('/'), x)):
        presupuesto.comprobar(entrada=True)
        fila = filas[ruta]
        partes = ruta.split('/')
        destino = etapa.joinpath(*partes)
        fuente = pp_root.joinpath(*partes)
        if fila['tipo'] == 'directorio':
            info = inv.inspeccionar(fuente)
            if info is None or not stat.S_ISDIR(info.st_mode): raise ValueError('Directorio ausente')
            destino.mkdir()
        elif fila['tipo'] == 'archivo':
            _copiar(fuente, destino, fila, presupuesto)
        else:
            raise ValueError('Storage incompleto')
    return nombre, {n: _huella(etapa / n, n) for n in _NOMBRES}


def _evento(root, clase, nombre, plan):
    return {'version': 1, 'operacion': plan['operacion'], 'inventario_sha256': plan['inventario_sha256'],
            'clase': clase, 'componente': nombre, 'etapa': plan['etapa'],
            'huella': (plan['activos'] if clase == 'conservar-activo' else plan['instalados'])[nombre]}


def _registro_evento(root, tipo, clase, nombre, plan):
    esperado = _evento(root, clase, nombre, plan)
    path = root / (tipo + '-' + clase + '-' + nombre + '.json')
    existente = des._leer(path)
    if existente is not None and not des._iguales(existente, esperado):
        raise ValueError('Evento contradictorio')
    return path, esperado, existente is not None


def _originales_conservados(root, evidencia, plan_original):
    for nombre in _NOMBRES:
        fila = plan_original['componentes'][nombre]
        if fila['tipo'] == 'ausente': raise ValueError('Original requerido ausente')
        evento = {'version': 1, 'operacion': evidencia['registro']['operacion'], 'componente': nombre,
                  'origen': plan_original['origenes'][nombre], 'destino': 'conservacion/' + nombre,
                  'inventario_sha256': evidencia['registro']['inventario']['sha256'], 'evidencia': fila}
        if not des._iguales(des._leer(root / ('intencion-' + nombre + '.json')), evento) or not des._iguales(des._leer(root / ('confirmacion-' + nombre + '.json')), evento):
            raise ValueError('Original no confirmado')
        des._verificar_arbol(root / nombre, nombre, evidencia['entradas'])


def _plan_valido(plan, evidencia):
    if not isinstance(plan, dict) or set(plan) != {'version', 'operacion', 'inventario_sha256', 'secuencia', 'etapa', 'instalados', 'activos'}:
        raise ValueError('Plan incompleto')
    if (type(plan['version']) is not int or plan['version'] != 1 or plan['operacion'] != evidencia['registro']['operacion']
            or plan['inventario_sha256'] != evidencia['registro']['inventario']['sha256']
            or type(plan['secuencia']) is not int or plan['secuencia'] != evidencia['registro']['secuencia']
            or not isinstance(plan['etapa'], str) or not re.fullmatch(r'instalacion-[0-9a-f]{32}', plan['etapa'])):
        raise ValueError('Plan contradictorio')
    for grupo in ('instalados', 'activos'):
        if not isinstance(plan[grupo], dict) or set(plan[grupo]) != set(_NOMBRES): raise ValueError('Componentes inválidos')
        for item in plan[grupo].values():
            if (not isinstance(item, dict) or set(item) != {'sha256', 'entradas', 'tipo'}
                    or not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256'])
                    or type(item['entradas']) is not int or item['entradas'] < 1
                    or item['tipo'] not in ('archivo', 'directorio', 'ausente')):
                raise ValueError('Huella inválida')
    if [plan['instalados'][n]['tipo'] for n in _NOMBRES] != ['archivo', 'directorio', 'archivo']:
        raise ValueError('Tipos preparados inválidos')
    return plan


def _mover(origen, destino):
    if origen == sel.DB_PATH or destino == sel.DB_PATH:
        cola._comprobar_auxiliares(sel.DB_PATH)
    if inv.inspeccionar(destino) is not None:
        raise ValueError('Destino ocupado')
    if origen.lstat().st_dev != destino.parent.lstat().st_dev:
        raise ValueError('Volúmenes distintos')
    os.rename(origen, destino)  # En Windows no sustituye un destino existente.


def _accion(operacion, confirmar):
    resultado = {'estado': 'bloqueada', 'listo_recuperacion': False}
    if os.name != 'nt' or not isinstance(operacion, str) or not re.fullmatch(r'operacion-[a-z0-9_]{8}', operacion) or confirmar != operacion:
        resultado['motivo'] = 'Operación o confirmación inválida.'
        return resultado
    try:
        evidencia = des._evidencia_registro(operacion)
        if evidencia['registro']['clave_origen'] != 'archivo' or os.environ.get('GESTOR_SECRET_KEY'):
            raise ValueError('Procedencia de clave no acreditada o configuración incompatible')
        root = r.DATA_DIR / des._nombre(operacion)
        if inv.inspeccionar(root) is None:
            inicial = {}
            seleccionado = sel._seleccionar(inicial)
            if seleccionado['estado'] != 'candidato identificado' or inicial['registro'] != evidencia['registro'] or pp._inspeccionar()['estado'] != 'preparación íntegra':
                raise ValueError('Selección no verificable')
            root = des._crear_plan_inicial(operacion, inicial, seleccionado)
        if not stat.S_ISDIR(inv.inspeccionar(root).st_mode): raise ValueError('Conservación no disponible')
        presupuesto = inv.Presupuesto()
        verificar_acl_raiz_conservacion(root, inv.limite('GESTOR_INVENTARIO_MAX_SEGUNDOS', 3600), presupuesto.max_entradas)
        for base in (root / 'previo-activo-base',):
            cola._comprobar_auxiliares(base)
        plan_original = des._cargar_plan(root, evidencia)
        des._publicar(r.RAIZ / operacion / 'inicio-recuperacion.json',
                      {'version': 1, 'operacion': operacion,
                       'inventario_sha256': evidencia['registro']['inventario']['sha256'],
                       'secuencia': evidencia['registro']['secuencia']})
        archivo_plan = root / 'instalacion.json'
        plan = des._leer(archivo_plan)
        if plan is None:
            des._comprobar_estado(root, evidencia, plan_original)
            activos = {n: _huella(p, n) for n, p in _activos().items()}
            if any(activos[n]['tipo'] not in (('directorio', 'ausente') if n == 'storage' else ('archivo', 'ausente')) for n in _NOMBRES):
                raise ValueError('Tipo activo inesperado')
            etapa, instalados = _crear_etapa(root, evidencia)
            for n in _NOMBRES:
                _comparar_con_preparacion(root / etapa / n, n, evidencia)
            plan = {'version': 1, 'operacion': operacion, 'inventario_sha256': evidencia['registro']['inventario']['sha256'],
                    'secuencia': evidencia['registro']['secuencia'], 'etapa': etapa, 'instalados': instalados, 'activos': activos}
            _plan_valido(plan, evidencia)
            # Antes de publicar, comprobar que los activos no cambiaron durante la copia.
            if any(_huella(p, n) != activos[n] for n, p in _activos().items()): raise ValueError('Activos cambiaron')
            des._publicar(archivo_plan, plan)
        plan = _plan_valido(plan, evidencia)
        etapa = root / plan['etapa']
        info = inv.inspeccionar(etapa)
        if info is None or not stat.S_ISDIR(info.st_mode): raise ValueError('Etapa ausente')
        if etapa.stat().st_dev != r.DATA_DIR.stat().st_dev: raise ValueError('Volumen diferente')
        cola._comprobar_auxiliares(etapa / 'base')
        # Validar el conjunto completo antes de efectuar más movimientos.
        for n, activo in _activos().items():
            src = etapa / n
            _, _, tiene_intencion = _registro_evento(root, 'intencion', 'instalar', n, plan)
            _, _, tiene_confirmacion = _registro_evento(root, 'confirmacion', 'instalar', n, plan)
            if tiene_confirmacion and not tiene_intencion:
                raise ValueError('Confirmación sin intención')
            if inv.inspeccionar(src) is not None:
                if tiene_confirmacion or _huella(src, n) != plan['instalados'][n]:
                    raise ValueError('Etapa alterada o contradictoria')
                _comparar_con_preparacion(src, n, evidencia)
            else:
                if not tiene_intencion or _huella(activo, n) != plan['instalados'][n]:
                    raise ValueError('Instalación incompleta o contradictoria')
                _comparar_con_preparacion(activo, n, evidencia)
        # Antes de la primera instalación, concluir desplazamientos originales.
        instalacion_iniciada = any(des._leer(root / ('intencion-instalar-' + n + '.json')) is not None for n in _NOMBRES)
        if not instalacion_iniciada:
            for n in _NOMBRES:
                movimiento = des._operar(operacion, confirmar, n, True)
                if movimiento['estado'] != 'desplazado confirmado': raise ValueError('Original no conservado')
        _originales_conservados(root, evidencia, plan_original)
        # Conservar cualquier componente activo que no sea el original ya desplazado.
        for nombre, activo in _activos().items():
            previo = root / ('previo-activo-' + nombre)
            esperado = plan['activos'][nombre]
            intentop, evento, existe_intento = _registro_evento(root, 'intencion', 'conservar-activo', nombre, plan)
            confp, _, existe_conf = _registro_evento(root, 'confirmacion', 'conservar-activo', nombre, plan)
            if esperado['tipo'] == 'ausente':
                if inv.inspeccionar(previo) is not None or existe_intento or existe_conf: raise ValueError('Ausencia contradictoria')
                continue
            conservado_original = _huella(root / nombre, nombre) == esperado
            if conservado_original:
                if inv.inspeccionar(previo) is not None or existe_intento or existe_conf: raise ValueError('Original duplicado')
                continue
            preservado = inv.inspeccionar(previo)
            if preservado is None:
                if existe_conf or _huella(activo, nombre) != esperado: raise ValueError('Activo anterior no verificable')
                des._publicar(intentop, evento)
                _mover(activo, previo)
            elif not existe_intento:
                raise ValueError('Activo guardado sin intención')
            if _huella(previo, nombre) != esperado: raise ValueError('Activo conservado cambió')
            des._publicar(confp, evento)
        # Instalar solo cuando todos los originales y activos previos estén preservados.
        for nombre, activo in _activos().items():
            src = etapa / nombre
            intentop, evento, existe_intento = _registro_evento(root, 'intencion', 'instalar', nombre, plan)
            confp, _, existe_conf = _registro_evento(root, 'confirmacion', 'instalar', nombre, plan)
            fuente, destino = inv.inspeccionar(src), inv.inspeccionar(activo)
            if fuente is not None and destino is None:
                if existe_conf or _huella(src, nombre) != plan['instalados'][nombre]: raise ValueError('Copia preparada alterada')
                _comparar_con_preparacion(src, nombre, evidencia)
                des._publicar(intentop, evento)
                _mover(src, activo)
            elif fuente is None and destino is not None:
                if not existe_intento: raise ValueError('Instalación sin intención')
            else:
                raise ValueError('Ubicación de instalación ambigua')
            if _huella(activo, nombre) != plan['instalados'][nombre]: raise ValueError('Componente instalado diferente')
            _comparar_con_preparacion(activo, nombre, evidencia)
            des._publicar(confp, evento)
        _originales_conservados(root, evidencia, plan_original)
        for n, p in _activos().items():
            if _huella(p, n) != plan['instalados'][n]: raise ValueError('Verificación final incompleta')
            _comparar_con_preparacion(p, n, evidencia)
        cola._comprobar_auxiliares(sel.DB_PATH)
        cola._comprobar_auxiliares(root / 'previo-activo-base')
        des._publicar(root / 'instalacion-verificada.json', {'version': 1, 'operacion': operacion, 'inventario_sha256': plan['inventario_sha256'], 'listo_recuperacion': False})
        resultado['estado'] = 'instalación verificada; arranque bloqueado'
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, sqlite3.Error, RecursionError, MemoryError, KeyboardInterrupt, subprocess.TimeoutExpired):
        resultado['motivo'] = 'Estado incompleto o contradictorio; conserve las evidencias y revise administrativamente.'
    return resultado
