"""Comprobación previa de recuperación; no modifica ni restaura datos activos.

El bloqueo de arranque y el registro v2 permanecen intactos. Esta comprobación
no constituye una autorización ni una promesa de que se pueda recuperar.
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
    # No se mueve nada: el selector vigente solo reconoce los originales en las
    # dos ubicaciones de restauración, no en una futura zona de cuarentena.
    resultado['motivo'] = ('Recuperación aún no implementada: falta integrar el registro de desplazamientos '
                           'y verificar las ACL necesarias para la cuenta del servicio.')
    return resultado


def main():
    from app.coordinacion import comprobar_recuperacion
    parser = argparse.ArgumentParser(description='Comprobación previa de recuperación; no restaura datos')
    parser.add_argument('--operacion', required=True)
    parser.add_argument('--confirmar-operacion', required=True)
    args = parser.parse_args()
    resultado = comprobar_recuperacion(args.operacion, args.confirmar_operacion)
    print(json.dumps(resultado, ensure_ascii=False))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
