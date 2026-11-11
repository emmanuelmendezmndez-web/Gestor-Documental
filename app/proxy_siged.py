"""Preparación y supervisión del proxy HTTPS del lanzador de Windows."""

import csv
import ipaddress
import os
import re
import shutil
import signal
import socket
import ssl
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPSConnection
from pathlib import Path

from app.parada_siged import custodiar_proceso


class ProxyNoDisponible(RuntimeError):
    pass


@dataclass(frozen=True)
class Proxy:
    host: str
    ejecutable: str
    archivo: Path
    externo: bool


@dataclass(frozen=True)
class CaddyPropio:
    proceso: subprocess.Popen
    cerrar_job: Callable[[], int]

    def poll(self):
        return self.proceso.poll()


def host_configurado():
    host = os.environ.get("SIGED_HOST", "").lower()
    etiquetas = host.split(".")
    if (len(host) > 253 or host == "localhost" or host.endswith(".localhost")
            or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", e) for e in etiquetas)):
        raise ProxyNoDisponible("Configure SIGED_HOST con el nombre DNS o IPv4 autorizado para HTTPS.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not re.search(r"[a-z]", host):
            raise ProxyNoDisponible("SIGED_HOST no es un nombre DNS o IPv4 válido.") from None
    else:
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
            raise ProxyNoDisponible("SIGED_HOST requiere una dirección estable accesible desde la LAN.")
    return host


def _externo():
    # La consulta solo emite estados. No expone argumentos ni cuentas del servicio.
    consulta = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_Service | Where-Object { "
        "$_.Name -match 'caddy' -or $_.DisplayName -match 'caddy' -or $_.PathName -match 'caddy\\.exe'"
        " } | ForEach-Object { $_.State }"
    )
    try:
        servicios = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", consulta],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.split()
        procesos = subprocess.run(
            ["tasklist.exe", "/fo", "csv", "/nh", "/fi", "IMAGENAME eq caddy.exe"],
            capture_output=True, text=True, timeout=15, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise ProxyNoDisponible("No se pudo comprobar si Caddy ya está administrado por Windows.") from None
    if "Running" in servicios or any(fila and fila[0].lower() == "caddy.exe" for fila in csv.reader(procesos.splitlines())):
        return True
    if servicios:
        raise ProxyNoDisponible("El servicio Caddy está detenido. Inícielo mediante su administración habitual.")
    return False


def preparar(raiz):
    host = host_configurado()
    ejecutable = shutil.which("caddy.exe")
    if not ejecutable:
        raise ProxyNoDisponible("Caddy no está disponible en PATH.")
    archivo = raiz / "Caddyfile.ejemplo"
    if not archivo.is_file():
        raise ProxyNoDisponible("Falta el archivo de configuración de Caddy de SIGED.")
    for clave in ("SIGED_CERT", "SIGED_KEY"):
        ruta = Path(os.environ.get(clave, ""))
        if not ruta.is_absolute() or not ruta.is_file():
            raise ProxyNoDisponible(f"Configure {clave} con su archivo PEM autorizado.")
    try:
        subprocess.run([ejecutable, "validate", "--config", str(archivo), "--adapter", "caddyfile"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError):
        raise ProxyNoDisponible("Caddy no pudo validar la configuración HTTPS. Revise la versión y los archivos TLS.") from None
    return Proxy(host, ejecutable, archivo, _externo())


def iniciar(proxy):
    if proxy.externo:
        return None
    try:
        with socket.socket() as comprobacion:
            comprobacion.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            comprobacion.bind(("0.0.0.0", 443))
    except OSError:
        raise ProxyNoDisponible("El puerto HTTPS 443 está ocupado o Windows no permite reservarlo.") from None
    try:
        proceso = subprocess.Popen(
            [proxy.ejecutable, "run", "--config", str(proxy.archivo), "--adapter", "caddyfile"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError:
        raise ProxyNoDisponible("Caddy no pudo iniciarse.") from None
    try:
        return CaddyPropio(proceso, custodiar_proceso(proceso.pid))
    except OSError:
        proceso.kill()
        proceso.wait(timeout=5)
        raise ProxyNoDisponible("Windows no pudo supervisar el proceso de Caddy.") from None


def verificar_tls(host, proceso):
    plazo = time.monotonic() + 12
    contexto = ssl.create_default_context()
    while time.monotonic() < plazo:
        if proceso is not None and proceso.poll() is not None:
            raise ProxyNoDisponible("Caddy se detuvo al arrancar. Revise el puerto 443 y la configuración.")
        conexion = HTTPSConnection(host, timeout=2, context=contexto)
        try:
            conexion.connect()
            return
        except ssl.SSLCertVerificationError:
            raise ProxyNoDisponible("El certificado HTTPS no es válido o su autoridad no es de confianza.") from None
        except OSError:
            time.sleep(.25)
        finally:
            conexion.close()
    raise ProxyNoDisponible("HTTPS no respondió. Revise DNS, Caddy y el puerto 443.")


def detener(caddy):
    if caddy is None:
        return
    proceso = caddy.proceso
    try:
        if proceso.poll() is None:
            try:
                proceso.send_signal(signal.CTRL_BREAK_EVENT)
                proceso.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass  # El Job cerrará el proceso en Windows.
    finally:
        caddy.cerrar_job()
    proceso.wait(timeout=5)
