"""Cierre explícito de una recuperación aplicada; no compara activos tras el cierre."""
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
from contextlib import closing

from app import constancia_preparacion as cp
from app import desplazamiento_original as des
from app import instalacion_recuperacion as instalacion
from app import inventario_restauracion as inv
from app import preparacion_cola as cola
from app import preparacion_persistente as pp
from app import registro_restauracion as r
from app import seleccion_originales as sel
from app.temporal_privado import verificar_acl_raiz_conservacion


def _sha(datos):
    return hashlib.sha256(json.dumps(datos, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def _evidencia_final(operacion):
    principal = r.leer(r.REGISTRO)
    if not principal or principal['version'] != 2 or principal['estado'] == 'finalizada' or principal['operacion'] != operacion:
        raise ValueError('Registro pendiente no coincide')
    final = dict(principal, estado='finalizada', paso='verificada')
    final['secuencia'] = r.secuencia(final['estado'], final['paso'], final['pasos'])
    r.analizar(final)
    # Solo se admite el final idéntico que pudo publicarse antes de un corte.
    evidencia = des._evidencia_registro(operacion, _final_esperado=final)
    return evidencia, final


def _verificar_activos(evidencia):
    op = evidencia['registro']['operacion']
    if evidencia['registro']['clave_origen'] != 'archivo' or os.environ.get('GESTOR_SECRET_KEY'):
        raise ValueError('Clave histórica no acreditada o configuración incompatible')
    root = r.DATA_DIR / des._nombre(op)
    info = inv.inspeccionar(root)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise ValueError('Conservación no disponible')
    presupuesto = inv.Presupuesto()
    verificar_acl_raiz_conservacion(root, inv.limite('GESTOR_INVENTARIO_MAX_SEGUNDOS', 3600), presupuesto.max_entradas)
    plan_original = des._cargar_plan(root, evidencia)
    plan = instalacion._plan_valido(des._leer(root / 'instalacion.json'), evidencia)
    etapa = root / plan['etapa']
    estado_etapa = inv.inspeccionar(etapa)
    if estado_etapa is None or not stat.S_ISDIR(estado_etapa.st_mode): raise ValueError('Etapa ausente')
    with os.scandir(etapa) as entradas_etapa:
        if next(entradas_etapa, None) is not None:
            raise ValueError('Etapa contiene componentes inesperados')
    instalacion._originales_conservados(root, evidencia, plan_original)
    cierre = des._leer(root / 'instalacion-verificada.json')
    esperado = {'version': 1, 'operacion': op, 'inventario_sha256': plan['inventario_sha256'], 'listo_recuperacion': False}
    if not des._iguales(cierre, esperado): raise ValueError('Instalación sin verificación')
    eventos = {}
    for nombre, activo in instalacion._activos().items():
        for tipo in ('intencion', 'confirmacion'):
            path, evento, existe = instalacion._registro_evento(root, tipo, 'instalar', nombre, plan)
            if not existe: raise ValueError('Instalación incompleta')
            eventos[path.name] = _sha(evento)
        if inv.inspeccionar(etapa / nombre) is not None: raise ValueError('Etapa aún contiene componente')
        if instalacion._huella(activo, nombre) != plan['instalados'][nombre]: raise ValueError('Identidad instalada diferente')
        instalacion._comparar_con_preparacion(activo, nombre, evidencia)
        previo = root / ('previo-activo-' + nombre)
        antiguo = plan['activos'][nombre]
        original = instalacion._huella(root / nombre, nombre) == antiguo
        for tipo in ('intencion', 'confirmacion'):
            path, evento, existe = instalacion._registro_evento(root, tipo, 'conservar-activo', nombre, plan)
            if antiguo['tipo'] != 'ausente' and not original:
                if not existe: raise ValueError('Estado previo no confirmado')
                eventos[path.name] = _sha(evento)
            elif existe: raise ValueError('Registro de estado previo contradictorio')
        if antiguo['tipo'] != 'ausente' and not original:
            if instalacion._huella(previo, nombre) != antiguo: raise ValueError('Estado previo alterado')
        elif inv.inspeccionar(previo) is not None:
            raise ValueError('Estado previo inesperado')
    for path in (sel.DB_PATH, root / 'base', root / 'previo-activo-base', etapa / 'base'):
        cola._comprobar_auxiliares(path)
    # Se abre solo la base instalada en modo de lectura, sin recuperación de journal.
    with closing(sqlite3.connect(sel.DB_PATH.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, inv.limite('GESTOR_VERIFICACION_MAX_CELDA', 16 * 1024**2))
        db.set_progress_handler(lambda: cola._interrumpir(presupuesto), 1000)
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA cache_size=-2048')
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',) or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite inválida')
        tablas = {fila[0] for fila in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'documentos' not in tablas: raise ValueError('Documentos ausentes')
        if 'expediente_documentos' in tablas and db.execute('SELECT 1 FROM expediente_documentos e LEFT JOIN documentos d ON d.id=e.documento_id LEFT JOIN expedientes x ON x.id=e.expediente_id WHERE d.id IS NULL OR x.id IS NULL LIMIT 1').fetchone():
            raise ValueError('Expediente inconsistente')
        for tabla, columna, prefijo in (('documentos', 'nombre_guardado', ''), ('avisos', 'imagen_guardada', 'avisos/'), ('usuarios', 'foto_perfil', 'perfiles/')):
            if tabla not in tablas: continue
            cols = {x[1] for x in db.execute('PRAGMA table_info(' + tabla + ')')}
            if columna not in cols: raise ValueError('Esquema incompleto')
            tamano = 'tamano_bytes' if tabla == 'documentos' and 'tamano_bytes' in cols else 'NULL'
            for nombre, size in db.execute(f'SELECT {columna}, {tamano} FROM {tabla}'):
                presupuesto.comprobar(entrada=True)
                if tabla != 'documentos' and not nombre: continue
                if not isinstance(nombre, str) or not nombre or nombre in ('.', '..') or '/' in nombre or '\\' in nombre:
                    raise ValueError('Referencia inválida')
                fila = evidencia['entradas'].get('storage/' + prefijo + nombre)
                if not fila or fila['tipo'] != 'archivo' or (size is not None and size != fila['tamano']):
                    raise ValueError('Referencia física inválida')
        cola_actual = cola._resumen(db, presupuesto)
    # La copia SQLite anterior se abre de manera aislada y de solo lectura.
    pp_root = r.DATA_DIR / pp._nombre(op)
    with closing(sqlite3.connect((pp_root / 'base').as_uri() + '?mode=ro&immutable=1', uri=True)) as anterior:
        anterior.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, inv.limite('GESTOR_VERIFICACION_MAX_CELDA', 16 * 1024**2))
        anterior.set_progress_handler(lambda: cola._interrumpir(presupuesto), 1000)
        anterior.execute('PRAGMA query_only=ON')
        anterior.execute('PRAGMA trusted_schema=OFF')
        cola_prevista = cola._resumen(anterior, presupuesto, True)
    if cola_actual[0] != cola_prevista[0] or cola_actual[1] != cola_prevista[1] or cola_actual[2] != 0:
        raise ValueError('Cola inconsistente')
    # Ninguna conexión queda abierta al tomar las huellas finales.
    for path in (sel.DB_PATH, root / 'base', root / 'previo-activo-base', etapa / 'base'):
        cola._comprobar_auxiliares(path)
    huellas = {n: instalacion._huella(p, n) for n, p in instalacion._activos().items()}
    if huellas != plan['instalados']: raise ValueError('Activos cambiaron durante la verificación')
    return root, plan, eventos, huellas


def _finalizar(operacion, confirmar):
    resultado = {'estado': 'bloqueada', 'listo_recuperacion': False}
    if not isinstance(operacion, str) or not re.fullmatch(r'operacion-[a-z0-9_]{8}', operacion) or confirmar != operacion:
        resultado['motivo'] = 'La confirmación debe coincidir con la operación.'
        return resultado
    try:
        principal = r.leer(r.REGISTRO)
        if principal and principal['estado'] == 'finalizada':
            if principal['operacion'] != operacion: raise ValueError('Operación distinta')
            r.comprobar_estado()
            validar_cierre_historico(principal)
            resultado.update(estado='restauración ya finalizada', listo_recuperacion=True)
            return resultado
        evidencia, final = _evidencia_final(operacion)
        root, plan, eventos, huellas = _verificar_activos(evidencia)
        des._publicar(r.RAIZ / operacion / 'inicio-recuperacion.json',
                      {'version': 1, 'operacion': operacion,
                       'inventario_sha256': evidencia['registro']['inventario']['sha256'],
                       'secuencia': evidencia['registro']['secuencia']})
        recibo = {'version': 1, 'operacion': operacion, 'inventario_sha256': evidencia['registro']['inventario']['sha256'],
                  'plan_sha256': _sha(plan), 'preparacion_sha256': _sha(cp.leer(r.DATA_DIR / pp._nombre(operacion))),
                  'eventos': eventos, 'huellas': huellas,
                  'listo_recuperacion': False}
        des._publicar(root / 'cierre-verificado.json', recibo)
        # Marca independiente dentro de la operación: no autoriza por sí sola.
        des._publicar(r.RAIZ / operacion / 'cierre-recuperacion.json', recibo)
        # Una nueva comprobación se hace antes de publicar el estado final.
        _, plan2, eventos2, huellas2 = _verificar_activos(evidencia)
        if plan2 != plan or eventos2 != eventos or huellas2 != huellas:
            raise ValueError('Estado cambió durante cierre')
        # Publicar sin reemplazo antes de actualizar el registro principal;
        # escribir() reconoce esta misma constancia y no la vuelve a crear.
        des._publicar(r.RAIZ / operacion / 'finalizada.json', final)
        r.escribir(final)
        r.comprobar_estado()
        resultado.update(estado='restauración finalizada', listo_recuperacion=True)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, sqlite3.Error, RecursionError, MemoryError, KeyboardInterrupt, RuntimeError, subprocess.TimeoutExpired):
        resultado['motivo'] = 'Cierre incompleto o evidencia contradictoria; conserve los archivos y revise administrativamente.'
    return resultado


def validar_cierre_historico(final, *, verificar_clave_efectiva=True):
    """Comprueba evidencia administrativa sin exigir que los activos sigan iguales."""
    if final.get('clave_origen') != 'archivo' or (verificar_clave_efectiva and os.environ.get('GESTOR_SECRET_KEY')):
        raise ValueError('La configuración efectiva de clave no está acreditada')
    op = final['operacion']
    directorio = r.RAIZ / op
    root = r.DATA_DIR / des._nombre(op)
    info = inv.inspeccionar(root)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise ValueError('Conservación histórica no disponible')
    recibo = des._leer(directorio / 'cierre-recuperacion.json')
    copia = des._leer(root / 'cierre-verificado.json')
    if not isinstance(recibo, dict) or set(recibo) != {'version', 'operacion', 'inventario_sha256', 'plan_sha256', 'preparacion_sha256', 'eventos', 'huellas', 'listo_recuperacion'} or not des._iguales(recibo, copia):
        raise ValueError('Cierre faltante o contradictorio')
    if (type(recibo['version']) is not int or recibo['version'] != 1 or recibo['operacion'] != op
            or recibo['inventario_sha256'] != final['inventario']['sha256'] or recibo['listo_recuperacion'] is not False
            or not isinstance(recibo['eventos'], dict)):
        raise ValueError('Cierre no vinculado')
    plan_original = des._leer(root / 'intenciones.json')
    if plan_original is None:
        raise ValueError('Plan original ausente')
    if not isinstance(plan_original, dict) or not isinstance(plan_original.get('registro'), dict):
        raise TypeError('Plan original inválido')
    previo = r.analizar(plan_original['registro'])
    if previo['estado'] == 'finalizada' or r.invariantes(previo) != r.invariantes(final):
        raise ValueError('Registro original no coincide')
    inicio_recuperacion = {'version': 1, 'operacion': op,
                           'inventario_sha256': final['inventario']['sha256'], 'secuencia': previo['secuencia']}
    if not des._iguales(des._leer(directorio / 'inicio-recuperacion.json'), inicio_recuperacion):
        raise ValueError('Inicio de recuperación no coincide')
    presupuesto = inv.Presupuesto()
    inv.verificar(directorio, final['inventario'], presupuesto)
    entradas = {}
    with (directorio / 'inventario.jsonl').open('rb') as archivo:
        while linea := archivo.readline(65537):
            presupuesto.comprobar(len(linea), entrada=True)
            if len(linea) > 65536 or not linea.endswith(b'\n'): raise ValueError('Inventario incompleto')
            fila = inv.json_estricto(linea)
            inv.validar_fila(fila)
            if fila['conjunto'] == 'anterior' and fila['ruta'] in ('base', 'storage', 'clave'):
                entradas[fila['ruta']] = {k: v for k, v in fila.items() if k not in ('conjunto', 'ruta')}
    if verificar_clave_efectiva:
        clave_actual = inv.inspeccionar(sel.SECRET_PATH)
        if clave_actual is None or not stat.S_ISREG(clave_actual.st_mode) or clave_actual.st_size == 0:
            raise ValueError('Clave local no disponible')
    evidencia = {'registro': previo, 'entradas': entradas}
    plan_original = des._cargar_plan(root, evidencia)
    plan = instalacion._plan_valido(des._leer(root / 'instalacion.json'), evidencia)
    if recibo['plan_sha256'] != _sha(plan) or not des._iguales(recibo['huellas'], plan['instalados']):
        raise ValueError('Plan de instalación no coincide')
    preparada = r.DATA_DIR / pp._nombre(op)
    info_preparada = inv.inspeccionar(preparada)
    if info_preparada is None or not stat.S_ISDIR(info_preparada.st_mode):
        raise ValueError('Preparación histórica no disponible')
    constancia = cp.leer(preparada)
    if constancia['operacion'] != op or constancia['inventario_sha256'] != final['inventario']['sha256'] or 'componentes' not in constancia or constancia['clave'] not in ('archivo identificado', 'configuracion incompatible'):
        raise ValueError('Constancia de preparación no coincide')
    if recibo['preparacion_sha256'] != _sha(constancia):
        raise ValueError('Constancia de preparación alterada')
    instalado = {'version': 1, 'operacion': op, 'inventario_sha256': final['inventario']['sha256'], 'listo_recuperacion': False}
    if not des._iguales(des._leer(root / 'instalacion-verificada.json'), instalado):
        raise ValueError('Instalación no confirmada')
    eventos = {}
    for nombre in instalacion._NOMBRES:
        fila = plan_original['componentes'][nombre]
        if fila['tipo'] == 'ausente': raise ValueError('Original requerido ausente')
        original = {'version': 1, 'operacion': op, 'componente': nombre, 'origen': plan_original['origenes'][nombre],
                    'destino': 'conservacion/' + nombre, 'inventario_sha256': final['inventario']['sha256'], 'evidencia': fila}
        for tipo in ('intencion', 'confirmacion'):
            if not des._iguales(des._leer(root / (tipo + '-' + nombre + '.json')), original):
                raise ValueError('Desplazamiento no confirmado')
            path, evento, existe = instalacion._registro_evento(root, tipo, 'instalar', nombre, plan)
            if not existe: raise ValueError('Instalación no confirmada')
            eventos[path.name] = _sha(evento)
        anteriores = []
        for tipo in ('intencion', 'confirmacion'):
            path, evento, existe = instalacion._registro_evento(root, tipo, 'conservar-activo', nombre, plan)
            anteriores.append(existe)
            if existe: eventos[path.name] = _sha(evento)
        if anteriores not in ([False, False], [True, True]): raise ValueError('Conservación parcial')
    if not des._iguales(eventos, recibo['eventos']):
        raise ValueError('Eventos de cierre no coinciden')
