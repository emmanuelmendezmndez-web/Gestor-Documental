"""Identificación conservadora; no prepara ni autoriza restauraciones."""
import hashlib
import json
import os
import re
import stat

from app import inventario_restauracion as inv
from app import registro_restauracion as r
from app.configuracion import DB_PATH, SECRET_PATH, STORAGE_DIR


class Rechazado(ValueError):
    pass


def _seleccionar(_evidencias=None):
    resultado = {'estado': 'evidencia insuficiente', 'listo_recuperacion': False}
    try:
        presupuesto = inv.Presupuesto()
        max_bytes = inv.limite('GESTOR_SELECCION_MAX_BYTES', 10 * 1024**3)
        principal = r.leer(r.REGISTRO)
        if not principal or principal['version'] != 2 or principal['estado'] == 'finalizada':
            raise ValueError('No hay registro v2 pendiente verificable')
        raiz = inv.inspeccionar(r.RAIZ)
        if raiz is None or not stat.S_ISDIR(raiz.st_mode):
            raise ValueError('Falta la raíz de evidencias')
        op = r.RAIZ / principal['operacion']
        info = inv.inspeccionar(op)
        if info is None or not stat.S_ISDIR(info.st_mode):
            raise ValueError('Falta la operación')
        inicio = r.leer(op / 'inicio.json')
        fin = r.leer(op / 'finalizada.json')
        legado = r.leer(op / 'finalizada-v1.json')
        if (not inicio or inicio['version'] != 2 or inicio['estado'] != 'iniciada'
                or r.invariantes(inicio) != r.invariantes(principal) or fin or legado):
            raise ValueError('Constancias ausentes, finales o contradictorias')
        # Las operaciones históricas solo se aceptan con constancias verificables.
        with os.scandir(r.RAIZ) as entradas:
            for entrada in entradas:
                presupuesto.comprobar(entrada=True)
                if entrada.name == op.name:
                    continue
                if not re.fullmatch(r'operacion-[a-z0-9_]{8}', entrada.name):
                    raise ValueError('Evidencia desconocida')
                otra = r.RAIZ / entrada.name
                estado = inv.inspeccionar(otra)
                if estado is None or not stat.S_ISDIR(estado.st_mode):
                    raise ValueError('Evidencia histórica inválida')
                previo = r.leer(otra / 'inicio.json')
                final = r.leer(otra / 'finalizada.json')
                antiguo = r.leer(otra / 'finalizada-v1.json')
                if previo:
                    if (previo['version'] != 2 or previo['estado'] != 'iniciada'
                            or previo['operacion'] != entrada.name or not final or final['estado'] != 'finalizada'
                            or r.invariantes(previo) != r.invariantes(final) or antiguo):
                        raise ValueError('Evidencia histórica incierta')
                    inv.verificar(otra, previo['inventario'], presupuesto)
                elif (not antiguo or antiguo['version'] != 1 or antiguo['estado'] != 'finalizada'
                      or antiguo['operacion'] != entrada.name or final or inv.inspeccionar(otra / 'inventario.jsonl')):
                    raise ValueError('Evidencia histórica incierta')
        inv.verificar(op, inicio['inventario'], presupuesto)
        esperado = {}
        digest = hashlib.sha256()
        with (op / 'inventario.jsonl').open('rb') as fuente:
            for linea in iter(lambda: fuente.readline(65537), b''):
                if len(linea) > 65536 or not linea.endswith(b'\n'):
                    raise ValueError('Inventario incompleto')
                presupuesto.comprobar(len(linea), entrada=True)
                digest.update(linea)
                fila = inv.json_estricto(linea)
                inv.validar_fila(fila)
                if fila['conjunto'] == 'anterior':
                    esperado[fila['ruta']] = {k: v for k, v in fila.items() if k not in ('conjunto', 'ruta')}
        if digest.hexdigest() != inicio['inventario']['sha256']:
            raise ValueError('Inventario cambió')
        if esperado.get('base', {}).get('tipo') != 'archivo' or esperado.get('storage', {}).get('tipo') != 'directorio':
            raise ValueError('Conjunto anterior incompleto')
        if principal['clave_origen'] == 'archivo' and esperado.get('clave', {}).get('tipo') != 'archivo':
            raise ValueError('Clave local anterior no acreditada')
        activos = {'base': DB_PATH, 'storage': STORAGE_DIR, 'clave': SECRET_PATH}
        for base in (DB_PATH, op / 'anterior-base'):
            for sufijo in ('-journal', '-wal', '-shm'):
                if inv.inspeccionar(base.parent / (base.name + sufijo)) is not None:
                    raise ValueError('Archivos auxiliares SQLite requieren revisión')
        ubicaciones = {}
        leido = 0

        def comparar(path, ruta, profundidad=0):
            nonlocal leido
            presupuesto.comprobar(entrada=True)
            if profundidad > 128:
                raise ValueError('Árbol demasiado profundo')
            info = inv.inspeccionar(path)
            if info is None:
                raise Rechazado('Falta un componente inventariado')
            fila = esperado.get(ruta)
            if fila is None:
                raise Rechazado('Hay archivos adicionales')
            if inv.identidad(info) != fila.get('identidad'):
                raise Rechazado('Identidad de componente diferente')
            if stat.S_ISREG(info.st_mode) and fila['tipo'] == 'archivo':
                if info.st_size != fila['tamano']:
                    raise Rechazado('Tamaño diferente')
                leido += info.st_size
                if leido > max_bytes:
                    raise ValueError('Límite de lectura excedido')
                if inv.huella(path, presupuesto) != fila:
                    raise Rechazado('Huella diferente')
            elif stat.S_ISDIR(info.st_mode) and fila['tipo'] == 'directorio':
                with os.scandir(path) as hijos:
                    for hijo in hijos:
                        comparar(path / hijo.name, ruta + '/' + hijo.name, profundidad + 1)
                despues = inv.inspeccionar(path)
                if despues is None or inv.identidad(despues) != fila['identidad']:
                    raise ValueError('Directorio cambió durante la inspección')
            else:
                raise Rechazado('Tipo diferente')
            vistos.add(ruta)

        vistos = set()
        for nombre, activo in activos.items():
            fila = esperado[nombre]
            guardado = op / ('anterior-' + nombre)
            if fila['tipo'] == 'ausente':
                if inv.inspeccionar(guardado) is not None or inv.inspeccionar(activo) is not None:
                    raise Rechazado('Existe un componente declarado originalmente ausente')
                vistos.add(nombre)
                ubicaciones[nombre] = 'originalmente ausente'
                continue
            coincidencias = []
            for ubicacion, path in (('guardado', guardado), ('activo', activo)):
                info = inv.inspeccionar(path)
                if info is not None and inv.identidad(info) == fila['identidad']:
                    coincidencias.append((ubicacion, path))
            if len(coincidencias) != 1:
                raise ValueError('Ubicación anterior ausente o ambigua')
            ubicacion, path = coincidencias[0]
            if nombre in ('base', 'storage') or principal['clave_origen'] == 'archivo':
                paso = r.CAMBIOS.index(nombre + '-guardar')
                secuencia = principal['secuencia']
                if (ubicacion == 'guardado' and secuencia < 2 * paso + 1) or (ubicacion == 'activo' and secuencia > 2 * paso + 1):
                    raise ValueError('Ubicación contradice el registro')
            comparar(path, nombre)
            ubicaciones[nombre] = ubicacion
        if vistos != set(esperado):
            raise Rechazado('Faltan entradas del conjunto anterior')
        resultado.update(estado='candidato identificado', operacion=principal['operacion'], componentes=ubicaciones,
                         clave_efectiva=('entorno no verificado' if principal['clave_origen'] == 'entorno' else 'archivo inventariado'))
        if _evidencias is not None:
            _evidencias.update(registro=principal, entradas=esperado,
                raices={n: (op / ('anterior-' + n) if ubicaciones[n] == 'guardado' else activos[n])
                        for n in activos})
    except Rechazado as error:
        resultado['estado'] = 'candidato rechazado'
        resultado['motivo'] = str(error)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError, KeyboardInterrupt):
        resultado['motivo'] = 'Evidencia incompleta, contradictoria o límite agotado; requiere revisión.'
    return resultado


def main():
    from app.coordinacion import seleccionar_originales
    print(json.dumps(seleccionar_originales(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
