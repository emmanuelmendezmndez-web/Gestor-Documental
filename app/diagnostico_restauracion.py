"""Informe administrativo conservador; no abre SQLite ni modifica evidencias."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import stat

from app import registro_restauracion as registro
from app import inventario_restauracion as inv
from app.configuracion import DB_PATH, STORAGE_DIR, SECRET_PATH


def _seguro(raiz, partes):
    """No seguir enlaces en ninguno de los componentes inspeccionados."""
    actual = raiz
    for parte in partes:
        info = inv.inspeccionar(actual)
        if info is None or not stat.S_ISDIR(info.st_mode):
            return None
        actual = actual / parte
    return actual


def _inspeccionar(modo='profundo'):
    if modo not in ('rapido', 'profundo'):
        raise ValueError('Modo de diagnóstico desconocido')
    informe = {"clasificacion": "información insuficiente o estado incierto", "operaciones": [],
               "modo": modo, "alcance": "La inspección no acredita recuperabilidad ni autenticidad; no abre SQLite ni analiza el contenido del ZIP."}
    try:
        presupuesto = inv.Presupuesto()
        max_lectura = inv.limite("GESTOR_DIAGNOSTICO_MAX_BYTES", 10 * 1024**3)
        max_detalles = inv.limite("GESTOR_DIAGNOSTICO_MAX_DETALLES", 10000)
        principal = registro.leer(registro.REGISTRO)
        raiz = inv.inspeccionar(registro.RAIZ)
        if raiz is None:
            informe["motivo"] = "No hay directorio de evidencias; no se puede acreditar un conjunto anterior."
            return informe
        if not stat.S_ISDIR(raiz.st_mode):
            raise ValueError("Directorio de evidencias inválido")
        bytes_leidos = 0
        with os.scandir(registro.RAIZ) as entradas:
            for entrada in entradas:
                presupuesto.comprobar(entrada=True)
                if not re.fullmatch(r"operacion-[a-z0-9_]{8}", entrada.name):
                    raise ValueError("Evidencia desconocida")
                carpeta = registro.RAIZ / entrada.name
                info = inv.inspeccionar(carpeta)
                if info is None or not stat.S_ISDIR(info.st_mode):
                    raise ValueError("Evidencia no disponible")
                inicio = registro.leer(carpeta / "inicio.json")
                fin = registro.leer(carpeta / "finalizada.json")
                legado = registro.leer(carpeta / "finalizada-v1.json")
                actual = principal if principal and principal['operacion'] == entrada.name else None
                op = {"operacion": entrada.name, "clasificacion": "información insuficiente o estado incierto"}
                informe['operaciones'].append(op)
                if inicio is None:
                    op['motivo'] = "Sin inventario v2 verificable; requiere revisión administrativa."
                    continue
                if (inicio['version'] != 2 or inicio['estado'] != 'iniciada' or inicio['operacion'] != entrada.name
                        or legado is not None or (actual and registro.invariantes(actual) != registro.invariantes(inicio))
                        or (fin and (fin['estado'] != 'finalizada' or registro.invariantes(fin) != registro.invariantes(inicio)))):
                    raise ValueError("Constancias contradictorias")
                inv.verificar(carpeta, inicio['inventario'], presupuesto)
                conteo = {"disponibles": 0, "ausentes": 0, "discrepantes": 0, "originalmente_ausentes": 0}
                op['detalles'] = []
                op['resumen'] = {}
                incompleto = actual is None or modo == 'rapido'
                discrepancia = False
                # Rutas se derivan de raíces fijas y entradas ya validadas por verificar().
                digest = hashlib.sha256()
                with (carpeta / 'inventario.jsonl').open('rb') as archivo:
                    for numero, linea in enumerate(iter(lambda: archivo.readline(65537), b''), 1):
                        if len(linea) > 65536 or not linea.endswith(b'\n'):
                            raise ValueError('Inventario inválido')
                        digest.update(linea)
                        presupuesto.comprobar(len(linea), entrada=True)
                        fila = inv.json_estricto(linea)
                        inv.validar_fila(fila)
                        if fila['tipo'] == 'ausente':
                            conteo['originalmente_ausentes'] += 1
                            categoria = 'originalmente ausente'
                            clave_resumen = fila['conjunto'] + ': ' + categoria
                            op['resumen'][clave_resumen] = op['resumen'].get(clave_resumen, 0) + 1
                            if len(op['detalles']) < max_detalles:
                                op['detalles'].append({'id': numero, 'conjunto': fila['conjunto'], 'categoria': categoria, 'area': fila['ruta'].split('/')[0]})
                            else:
                                incompleto = True
                            continue
                        partes = fila['ruta'].split('/')
                        antiguas = {'base': carpeta / 'anterior-base', 'storage': carpeta / 'anterior-storage', 'clave': carpeta / 'anterior-clave'}
                        activas = {'base': DB_PATH, 'storage': STORAGE_DIR, 'clave': SECRET_PATH}
                        preparados = {'base': carpeta / 'validado' / 'database' / 'gestor.db', 'storage': carpeta / 'validado' / 'storage', 'clave': carpeta / 'validado' / 'secrets' / 'session_key'}
                        if fila['conjunto'] == 'anterior':
                            raices = (antiguas[partes[0]], activas[partes[0]])
                        elif fila['conjunto'] == 'preparado':
                            raices = (preparados[partes[0]],)
                        else:
                            raices = (registro.BACKUP_DIR / Path(inicio['respaldo_previo']).name,)
                        candidatos = [_seguro(registro.DATA_DIR, (raiz_c / Path(*partes[1:])).relative_to(registro.DATA_DIR).parts) for raiz_c in raices]
                        anterior_presente, coincide = False, False
                        categoria = 'archivo ausente'
                        for indice, candidato in enumerate(candidatos):
                            if candidato is None:
                                continue
                            info_c = inv.inspeccionar(candidato)
                            if info_c is None:
                                continue
                            if indice == 0:
                                anterior_presente = True
                            if fila['tipo'] == 'directorio':
                                if not stat.S_ISDIR(info_c.st_mode):
                                    categoria = 'tipo inesperado'
                                elif inv.identidad(info_c) != fila['identidad']:
                                    categoria = 'identidad inconsistente'
                                else:
                                    coincide = True
                                    break
                                continue
                            if not stat.S_ISREG(info_c.st_mode):
                                categoria = 'tipo inesperado'
                                continue
                            if info_c.st_size != fila['tamano']:
                                categoria = 'tamaño diferente'
                                continue
                            if modo == 'rapido':
                                categoria = 'sin verificar'
                                continue
                            bytes_leidos += info_c.st_size
                            if bytes_leidos > max_lectura:
                                raise ValueError('Límite de lectura del diagnóstico excedido')
                            huella = inv.huella(candidato, presupuesto)
                            if huella['sha256'] != fila['sha256']:
                                categoria = 'hash diferente'
                                continue
                            if huella['identidad'] != fila['identidad']:
                                categoria = 'identidad inconsistente'
                                continue
                            if huella['sha256'] == fila['sha256']:
                                coincide = True
                                break
                        if coincide:
                            categoria = 'verificado'
                        if fila['conjunto'] == 'anterior' and fila['tipo'] == 'archivo':
                            conteo['disponibles' if coincide else 'discrepantes' if anterior_presente and categoria != 'sin verificar' else 'ausentes'] += 1
                        if categoria != 'verificado':
                            incompleto = True
                            if categoria not in ('sin verificar', 'archivo ausente') and (fila['conjunto'] != 'anterior' or anterior_presente):
                                discrepancia = True
                        clave_resumen = fila['conjunto'] + ': ' + categoria
                        op['resumen'][clave_resumen] = op['resumen'].get(clave_resumen, 0) + 1
                        if len(op['detalles']) < max_detalles:
                            op['detalles'].append({'id': numero, 'conjunto': fila['conjunto'], 'categoria': categoria, 'area': partes[0]})
                        else:
                            incompleto = True
                if digest.hexdigest() != inicio['inventario']['sha256']:
                    raise ValueError('Inventario cambió durante la inspección')
                op['archivos_anteriores'] = conteo
                op['clasificacion'] = ('discrepancia comprobada' if discrepancia else
                                       'información insuficiente o estado incierto' if incompleto else
                                       'evidencia coherente')
                if len(op['detalles']) >= max_detalles:
                    op['aviso'] = 'Detalles limitados; pueden existir archivos no enumerados.'
        if principal and not any(op['operacion'] == principal['operacion'] for op in informe['operaciones']):
            informe['motivo'] = 'Falta el directorio correspondiente al registro principal.'
        elif informe['operaciones']:
            clases = [op['clasificacion'] for op in informe['operaciones']]
            informe['clasificacion'] = ('discrepancia comprobada' if 'discrepancia comprobada' in clases else
                                        'información insuficiente o estado incierto' if 'información insuficiente o estado incierto' in clases else
                                        'evidencia coherente')
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, KeyboardInterrupt):
        informe['clasificacion'] = 'información insuficiente o estado incierto'
        informe['motivo'] = 'Inspección incompleta o sin verificar: registro o evidencia ilegible, contradictoria o superior a los límites; conserve todo para revisión.'
    return informe


def main():
    from app.coordinacion import diagnosticar_restauracion
    parser = argparse.ArgumentParser(description='Diagnóstico de restauraciones sin modificar datos')
    parser.add_argument('--modo', choices=('rapido', 'profundo'), default='profundo')
    args = parser.parse_args()
    print(json.dumps(diagnosticar_restauracion(args.modo), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
