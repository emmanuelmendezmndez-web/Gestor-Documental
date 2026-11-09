"""Comprobación y aplicación administrativa con arranque bloqueado.

La comprobación no modifica datos. La aplicación conserva las fuentes y usa
intenciones y confirmaciones persistentes; ninguna acción habilita el arranque.
"""
import argparse
import json
import os
import re

from app import preparacion_persistente as preparacion
from app import registro_restauracion as registro
from app import seleccion_originales as selector


def _comprobar(operacion, confirmacion):
    resultado = {'estado': 'bloqueada', 'listo_recuperacion': False}
    if (not isinstance(operacion, str) or not re.fullmatch(r'operacion-[a-z0-9_]{8}', operacion)
            or confirmacion != operacion):
        resultado['motivo'] = 'La confirmación debe coincidir con la operación seleccionada.'
        return resultado
    evidencia = {}
    seleccion = selector._seleccionar(evidencia)
    if seleccion['estado'] != 'candidato identificado':
        resultado['motivo'] = 'No se pudo verificar el conjunto anterior.'
        return resultado
    if evidencia['registro']['operacion'] != operacion:
        resultado['motivo'] = 'La operación indicada no coincide con el registro pendiente.'
        return resultado
    informe = preparacion._inspeccionar()
    if informe['estado'] != 'preparación íntegra':
        resultado['motivo'] = 'La preparación está incompleta, es contradictoria o no verificable.'
        return resultado
    if evidencia['registro']['clave_origen'] == 'entorno':
        resultado['motivo'] = 'No se ha acreditado la procedencia de la clave histórica de entorno.'
        return resultado
    if os.environ.get('GESTOR_SECRET_KEY'):
        resultado['motivo'] = 'La configuración actual de clave no corresponde a la procedencia local registrada.'
        return resultado
    if informe.get('clave') != 'archivo histórico identificado; autenticidad no comprobada':
        resultado['motivo'] = 'No se ha identificado la clave local histórica.'
        return resultado
    # La comprobación no autoriza ni aplica la instalación.
    resultado['motivo'] = ('Comprobación previa: no autoriza la recuperación; la aplicación requiere '
                           'su acción explícita y el arranque continúa bloqueado.')
    return resultado


def main():
    from app.coordinacion import BloqueoNoDisponible, comprobar_recuperacion, aplicar_recuperacion
    parser = argparse.ArgumentParser(description='Recuperación administrativa con arranque bloqueado')
    parser.add_argument('accion', choices=('comprobar', 'aplicar'), nargs='?', default='comprobar')
    parser.add_argument('--operacion', required=True)
    parser.add_argument('--confirmar-operacion', required=True)
    args = parser.parse_args()
    accion = aplicar_recuperacion if args.accion == 'aplicar' else comprobar_recuperacion
    try:
        resultado = accion(args.operacion, args.confirmar_operacion)
    except BloqueoNoDisponible:
        resultado = {'estado': 'bloqueada', 'listo_recuperacion': False,
                     'motivo': 'No se pudo adquirir el bloqueo exclusivo; detenga SIGED y revise el acceso.'}
    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado['estado'] == 'instalación verificada; arranque bloqueado' else 1


if __name__ == '__main__':
    raise SystemExit(main())
