"""Configuración y primera inicialización de Mensajería en la beta."""

import os
import socket
from hashlib import sha256
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

REDES_LAN = tuple(IPv4Network(red) for red in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def _perfil(raiz):
    identificador = sha256(str(raiz).casefold().encode()).hexdigest()[:20]
    return Path(os.environ["LOCALAPPDATA"]) / "SIGED" / "beta" / identificador


def elegir_ip(solicitada):
    direcciones = sorted({
        dato[4][0] for dato in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        if any(IPv4Address(dato[4][0]) in red for red in REDES_LAN)
    }, key=IPv4Address)
    if solicitada:
        if solicitada not in direcciones:
            raise ValueError("La dirección indicada no es una IPv4 privada de este equipo.")
        return solicitada
    if not direcciones:
        raise ValueError("No se encontró una IPv4 privada para la demostración LAN.")
    if len(direcciones) == 1:
        return direcciones[0]
    print("Seleccione la IPv4 de la red compartida con los dispositivos de prueba:")
    for numero, direccion in enumerate(direcciones, 1):
        print(f"  {numero}. {direccion}")
    opcion = input("Número: ").strip()
    if opcion not in {str(n) for n in range(1, len(direcciones) + 1)}:
        raise ValueError("Seleccione una de las direcciones mostradas.")
    return direcciones[int(opcion) - 1]


def preparar():
    from app.configuracion import DATA_DIR, DB_PATH
    from app.mensajeria import base_datos, reconciliacion
    from app.mensajeria.configuracion import directorio_configurado
    from app.temporal_privado import verificar_acl_base_privada

    if not DB_PATH.is_file():
        raise ValueError(f"No se encontró la base principal de SIGED en {DB_PATH}.")
    if not os.environ.get("GESTOR_MENSAJERIA_DIR", "").strip():
        perfil = _perfil(DATA_DIR)
        perfil.mkdir(parents=True, exist_ok=True)
        os.environ["GESTOR_MENSAJERIA_DIR"] = str(perfil / ".siged-mensajeria")
    almacen = directorio_configurado()
    if not (almacen / base_datos.NOMBRE_BASE).exists():
        base_datos.inicializar()
    estado = reconciliacion.diagnosticar()
    if estado["estado"] == "generacion_desconocida":
        estado = reconciliacion.preparar_identidades()
    if estado["estado"] == "vinculo_pendiente":
        estado = reconciliacion.reconciliar(estado["confirmacion"])
    if estado["estado"] != "identidad_coherente":
        raise ValueError(f"El almacén de Mensajería requiere revisión ({estado['estado']}).")
    # Verifica la misma ACL que HTTP y WS, fuera del plazo de sus consultas.
    verificar_acl_base_privada(almacen, base_datos.NOMBRE_BASE, 30)
