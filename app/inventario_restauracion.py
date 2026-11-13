"""Inventarios acotados e inmutables. Los hashes indican integridad, no autenticidad."""
import hashlib
import json
import os
import re
import stat
import time
import unicodedata
from pathlib import Path

from app.configuracion import DB_PATH, SECRET_PATH, STORAGE_DIR


def pares_unicos(pares):
    resultado = {}
    for clave, valor in pares:
        if clave in resultado:
            raise ValueError("Claves JSON duplicadas")
        resultado[clave] = valor
    return resultado


def json_estricto(texto):
    def invalido(valor):
        raise ValueError("Constante JSON no permitida")
    return json.loads(texto, object_pairs_hook=pares_unicos, parse_constant=invalido)


def limite(nombre, defecto):
    valor = int(os.environ.get(nombre, defecto))
    if valor <= 0:
        raise ValueError("El límite debe ser un entero positivo")
    return valor


class Presupuesto:
    def __init__(self):
        self.fin = time.monotonic() + limite("GESTOR_INVENTARIO_MAX_SEGUNDOS", 3600)
        self.max_entradas = limite("GESTOR_INVENTARIO_MAX_ENTRADAS", 300000)
        self.max_bytes = limite("GESTOR_INVENTARIO_MAX_BYTES", 256 * 1024**2)
        self.entradas = self.bytes = 0

    def comprobar(self, longitud=0, entrada=False):
        self.bytes += longitud
        self.entradas += int(entrada)
        if time.monotonic() > self.fin or self.bytes > self.max_bytes or self.entradas > self.max_entradas:
            raise ValueError("Inventario supera el presupuesto de recursos")


def inspeccionar(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("No se permiten enlaces ni puntos de reanálisis")
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("Tipo de archivo no permitido")
    return info


def identidad(info):
    return {"volumen": info.st_dev, "archivo": info.st_ino, "mtime_ns": info.st_mtime_ns}


def huella(path, presupuesto):
    antes = inspeccionar(path)
    if antes is None or not stat.S_ISREG(antes.st_mode):
        raise ValueError("Archivo no disponible")
    digest = hashlib.sha256()
    cantidad = 0
    with path.open("rb") as archivo:
        abierto = os.fstat(archivo.fileno())
        if identidad(abierto) != identidad(antes):
            raise ValueError("Archivo cambió durante su apertura")
        for bloque in iter(lambda: archivo.read(1024**2), b""):
            presupuesto.comprobar()
            digest.update(bloque)
            cantidad += len(bloque)
        despues = os.fstat(archivo.fileno())
    actual = inspeccionar(path)
    if (actual is None or identidad(antes) != identidad(despues) or identidad(antes) != identidad(actual)
            or cantidad != antes.st_size or cantidad != despues.st_size or cantidad != actual.st_size):
        raise ValueError("Archivo cambió durante el inventario")
    return {"tipo": "archivo", "tamano": cantidad, "sha256": digest.hexdigest(), "identidad": identidad(antes)}


def recorrer(path, ruta, presupuesto, profundidad=0):
    presupuesto.comprobar()
    if profundidad > 128:
        raise ValueError("Inventario demasiado profundo")
    info = inspeccionar(path)
    if info is None:
        yield {"ruta": ruta, "tipo": "ausente"}
    elif stat.S_ISREG(info.st_mode):
        yield {"ruta": ruta, **huella(path, presupuesto)}
    else:
        yield {"ruta": ruta, "tipo": "directorio", "identidad": identidad(info)}
        with os.scandir(path) as hijos:
            for hijo in hijos:
                yield from recorrer(Path(hijo.path), ruta + "/" + hijo.name, presupuesto, profundidad + 1)
        actual = inspeccionar(path)
        if actual is None or identidad(info) != identidad(actual):
            raise ValueError("Directorio cambió durante el inventario")


def publicar(directorio, previo):
    presupuesto = Presupuesto()
    preparado = directorio / "validado"
    conjuntos = {
        "anterior": {"base": DB_PATH, "storage": STORAGE_DIR, "clave": SECRET_PATH},
        "preparado": {"base": preparado / "database" / "gestor.db", "storage": preparado / "storage", "clave": preparado / "secrets" / "session_key"},
        "respaldo": {"zip": previo},
    }
    digest = hashlib.sha256()
    # xb impide sustituir incluso un inventario incompleto de un intento anterior.
    with (directorio / "inventario.jsonl").open("xb") as salida:
        for conjunto, raices in conjuntos.items():
            for ruta, path in raices.items():
                for datos in recorrer(path, ruta, presupuesto):
                    fila = {"conjunto": conjunto, **datos}
                    validar_fila(fila)
                    linea = (json.dumps(fila, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
                    if len(linea) > 65536:
                        raise ValueError("Entrada de inventario demasiado grande")
                    presupuesto.comprobar(len(linea), entrada=True)
                    salida.write(linea)
                    digest.update(linea)
        salida.flush()
        os.fsync(salida.fileno())
    return {"sha256": digest.hexdigest(), "bytes": presupuesto.bytes, "entradas": presupuesto.entradas}


def validar_fila(fila):
    if not isinstance(fila, dict):
        raise TypeError("Entrada de inventario inválida")
    conjunto, ruta, tipo = (fila.get(k) for k in ("conjunto", "ruta", "tipo"))
    raices = {"anterior": {"base", "storage", "clave"}, "preparado": {"base", "storage", "clave"}, "respaldo": {"zip"}}
    if not isinstance(conjunto, str) or conjunto not in raices or not isinstance(ruta, str):
        raise ValueError("Conjunto no permitido")
    partes = ruta.split("/")
    if partes[0] not in raices[conjunto] or (len(partes) > 1 and partes[0] != "storage"):
        raise ValueError("Ruta fuera del conjunto")
    for parte in partes:
        if (not parte or parte in {".", ".."} or parte.endswith((" ", "."))
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in parte)
                or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", parte, re.IGNORECASE)):
            raise ValueError("Ruta no segura")
    campos = {"conjunto", "ruta", "tipo"}
    if tipo == "archivo":
        if ruta == "storage":
            raise ValueError("La raíz storage debe ser un directorio o estar ausente")
        campos |= {"tamano", "sha256", "identidad"}
        if type(fila.get("tamano")) is not int or fila["tamano"] < 0 or not isinstance(fila.get("sha256"), str) or not re.fullmatch("[0-9a-f]{64}", fila["sha256"]):
            raise ValueError("Tamaño o hash inválido")
    elif tipo == "directorio":
        if partes[0] != "storage":
            raise ValueError("Directorio no permitido")
        campos.add("identidad")
    elif tipo != "ausente" or len(partes) != 1:
        raise ValueError("Tipo o ausencia inválidos")
    if set(fila) != campos:
        raise ValueError("Campos de inventario inesperados")
    if "identidad" in fila:
        ident = fila["identidad"]
        if not isinstance(ident, dict) or set(ident) != {"volumen", "archivo", "mtime_ns"} or any(type(v) is not int for v in ident.values()):
            raise ValueError("Identidad inválida")


def verificar(directorio, descriptor, presupuesto=None):
    presupuesto = presupuesto or Presupuesto()
    archivo = directorio / "inventario.jsonl"
    info = inspeccionar(archivo)
    if info is None or not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["bytes"]:
        raise ValueError("Inventario faltante o de tamaño incorrecto")
    digest = hashlib.sha256()
    vistos = {}
    cantidad = total = 0
    with archivo.open("rb") as fuente:
        while linea := fuente.readline(65537):
            if len(linea) > 65536 or not linea.endswith(b"\n"):
                raise ValueError("Inventario truncado o entrada excesiva")
            presupuesto.comprobar(len(linea), entrada=True)
            fila = json_estricto(linea)
            validar_fila(fila)
            normal = unicodedata.normalize("NFC", fila["ruta"]).casefold()
            clave = (fila["conjunto"], normal)
            if clave in vistos:
                raise ValueError("Entradas duplicadas o equivalentes")
            partes = fila["ruta"].split("/")
            if len(partes) > 129:
                raise ValueError("Inventario demasiado profundo")
            padre = unicodedata.normalize("NFC", "/".join(partes[:-1])).casefold()
            if len(partes) > 1 and vistos.get((fila["conjunto"], padre)) != "directorio":
                raise ValueError("Padre ausente o contradictorio")
            vistos[clave] = fila["tipo"]
            digest.update(linea)
            cantidad += 1
            total += len(linea)
    for conjunto, rutas in (("anterior", ("base", "storage", "clave")), ("preparado", ("base", "storage", "clave")), ("respaldo", ("zip",))):
        for ruta in rutas:
            if (conjunto, ruta) not in vistos:
                raise ValueError("Inventario incompleto")
            if conjunto != "anterior" and vistos[conjunto, ruta] != ("directorio" if ruta == "storage" else "archivo"):
                raise ValueError("Conjunto preparado o respaldo incompleto")
    if (digest.hexdigest(), total, cantidad) != (descriptor["sha256"], descriptor["bytes"], descriptor["entradas"]):
        raise ValueError("Inventario no coincide con el registro")
    return {ruta: vistos['anterior', ruta] for ruta in ('base', 'storage', 'clave')}
