"""Esquemas v1/v2 y evidencias históricas; consultar bajo bloqueo de datos."""
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from app.configuracion import BACKUP_DIR, DATA_DIR
from app.inventario_restauracion import (
    Presupuesto,
    inspeccionar,
    json_estricto,
    verificar,
)

REGISTRO = DATA_DIR / ".siged-restauracion.json"
RAIZ = DATA_DIR / ".siged-restauraciones"
AVISO = ("Restauración pendiente o evidencia incierta/ilegible. Detenga SIGED y conserve "
         "el registro, el directorio de trabajo y los respaldos para recuperación manual.")
BASE = {"version", "operacion", "directorio", "respaldo_previo", "estado", "paso"}
CAMBIOS = ["base-guardar", "base-instalar", "storage-guardar", "storage-instalar", "clave-guardar", "clave-instalar"]


def analizar(datos):
    """Valida estructura y rutas sin abrir ninguna ruta indicada por el registro."""
    if not isinstance(datos, dict) or type(datos.get("version")) is not int or datos["version"] not in (1, 2):
        raise ValueError("Versión de registro desconocida")
    v2 = datos["version"] == 2
    if set(datos) != BASE | ({"inventario", "clave_origen", "pasos", "secuencia"} if v2 else set()):
        raise ValueError("Campos de registro inválidos")
    op = datos["operacion"]
    if not isinstance(op, str) or not re.fullmatch(r"operacion-[a-z0-9_]{8}", op):
        raise ValueError("Identificador de operación inválido")
    if datos["directorio"] != str(RAIZ / op):
        raise ValueError("Directorio fuera de la ubicación permitida")
    previo = datos["respaldo_previo"]
    if (not isinstance(previo, str) or not re.fullmatch(r"previo-restauracion-\d{8}-\d{6}\.zip", Path(previo).name)
            or previo != str(BACKUP_DIR / Path(previo).name)):
        raise ValueError("Respaldo fuera de la ubicación permitida")
    estado, paso = datos["estado"], datos["paso"]
    if not isinstance(estado, str) or not isinstance(paso, str):
        raise TypeError("Estado inválido")
    if not ((estado, paso) in {("iniciada", "preparada"), ("pendiente", "verificacion"), ("finalizada", "verificada")}
            or (estado in {"pendiente", "confirmada"} and paso in CAMBIOS)):
        raise ValueError("Estado y paso contradictorios")
    if v2:
        origen, pasos = datos["clave_origen"], datos["pasos"]
        permitidos = [CAMBIOS[:4]] if origen == "entorno" else [CAMBIOS] if origen == "archivo" else []
        if pasos not in permitidos:
            raise ValueError("Plan incompatible con el origen de la clave")
        if paso in CAMBIOS and paso not in pasos:
            raise ValueError("Paso fuera del plan")
        if type(datos["secuencia"]) is not int or datos["secuencia"] != secuencia(estado, paso, pasos):
            raise ValueError("Secuencia contradictoria")
        inv = datos["inventario"]
        if (not isinstance(inv, dict) or set(inv) != {"sha256", "bytes", "entradas"}
                or not isinstance(inv["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", inv["sha256"])
                or any(type(inv[k]) is not int or inv[k] <= 0 for k in ("bytes", "entradas"))):
            raise ValueError("Descriptor de inventario inválido")
    return datos


def secuencia(estado, paso, pasos):
    if estado == "iniciada":
        return 0
    if paso == "verificacion":
        return 2 * len(pasos) + 1
    if estado == "finalizada":
        return 2 * len(pasos) + 2
    return 2 * pasos.index(paso) + (1 if estado == "pendiente" else 2)


def leer(path):
    info = inspeccionar(path)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
        raise ValueError("Registro no regular o demasiado grande")
    with path.open("rb") as archivo:
        contenido = archivo.read(65537)
    if len(contenido) > 65536:
        raise ValueError("Registro demasiado grande")
    return analizar(json_estricto(contenido))


def invariantes(datos):
    return {k: v for k, v in datos.items() if k not in {"estado", "paso", "secuencia"}}


def comprobar_estado(*, con_generacion=False):
    """No compara datos activos con inventarios históricos tras uso legítimo de SIGED."""
    try:
        principal = leer(REGISTRO)
        if principal is not None and principal["estado"] != "finalizada":
            raise ValueError("Operación incompleta")
        raiz = inspeccionar(RAIZ)
        encontrados = set()
        evidencias = {}
        presupuesto = Presupuesto()
        if raiz is not None:
            if not stat.S_ISDIR(raiz.st_mode):
                raise ValueError("Directorio de evidencias inválido")
            with os.scandir(RAIZ) as entradas:
                for entrada in entradas:
                    presupuesto.comprobar(entrada=True)
                    if not re.fullmatch(r"operacion-[a-z0-9_]{8}", entrada.name):
                        raise ValueError("Evidencia desconocida")
                    directorio = RAIZ / entrada.name
                    info = inspeccionar(directorio)
                    if info is None or not stat.S_ISDIR(info.st_mode):
                        raise ValueError("Operación no disponible")
                    encontrados.add(entrada.name)
                    inicio = leer(directorio / "inicio.json")
                    fin = leer(directorio / "finalizada.json")
                    legado = leer(directorio / "finalizada-v1.json")
                    if inicio is not None:
                        if (inicio["version"] != 2 or inicio["estado"] != "iniciada" or inicio["operacion"] != entrada.name
                                or fin is None or fin["version"] != 2 or fin["estado"] != "finalizada"
                                or invariantes(inicio) != invariantes(fin) or legado is not None):
                            raise ValueError("Evidencia pendiente o contradictoria")
                        anterior = verificar(directorio, inicio["inventario"], presupuesto)
                        if (anterior['base'] != 'archivo' or anterior['storage'] != 'directorio'
                                or (inicio['clave_origen'] == 'archivo' and anterior['clave'] != 'archivo')):
                            raise ValueError("El plan contradice las presencias originales")
                        if principal is not None and principal["operacion"] == entrada.name and principal != fin:
                            raise ValueError("Registro principal no coincide con su constancia")
                        # Un cierre de recuperación requiere varias evidencias coherentes;
                        # no se vuelven a comparar activos modificables tras el arranque.
                        conservacion = DATA_DIR / ('.siged-conservacion-' + entrada.name)
                        info_conservacion = inspeccionar(conservacion)
                        if info_conservacion is not None and not stat.S_ISDIR(info_conservacion.st_mode):
                            raise ValueError('Conservación no disponible')
                        preparada = DATA_DIR / ('.siged-preparacion-' + entrada.name)
                        info_preparada = inspeccionar(preparada)
                        if info_preparada is not None and not stat.S_ISDIR(info_preparada.st_mode):
                            raise ValueError('Preparación no disponible')
                        marcador = inspeccionar(directorio / 'cierre-recuperacion.json')
                        if (marcador is not None or inspeccionar(directorio / 'inicio-recuperacion.json') is not None
                                or info_preparada is not None
                                or (info_conservacion is not None and
                                    (inspeccionar(conservacion / 'instalacion.json') is not None
                                     or inspeccionar(conservacion / 'cierre-verificado.json') is not None))):
                            from app.cierre_recuperacion import validar_cierre_historico
                            validar_cierre_historico(fin, verificar_clave_efectiva=(principal is None or principal['operacion'] == entrada.name))
                        if con_generacion:
                            evidencias[entrada.name] = fin
                    else:
                        # v1 conserva lo que se registró; no fabrica inventarios.
                        conocido = legado or (principal if principal and principal["operacion"] == entrada.name else None)
                        if (fin is not None or conocido is None or conocido["version"] != 1
                                or conocido["estado"] != "finalizada" or conocido["operacion"] != entrada.name
                                or inspeccionar(directorio / "inventario.jsonl") is not None):
                            raise ValueError("Operación antigua incierta")
                        if principal and principal["operacion"] == entrada.name and principal != conocido:
                            raise ValueError("Constancia antigua contradictoria")
                        if con_generacion:
                            evidencias[entrada.name] = conocido
        if principal is not None and principal["operacion"] not in encontrados:
            raise ValueError("Falta el directorio de la operación")
        if con_generacion:
            contenido = json.dumps([principal, evidencias], sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(contenido.encode("utf-8")).hexdigest()
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise RuntimeError(AVISO) from error


def _inmutable(path, datos):
    if inspeccionar(path) is not None:
        if leer(path) != datos:
            raise ValueError("No se sobrescribe evidencia existente")
        return
    with path.open("xb") as archivo:
        archivo.write(json.dumps(datos, ensure_ascii=True).encode())
        archivo.flush()
        os.fsync(archivo.fileno())


def conservar_legado():
    """Solo bajo bloqueo exclusivo, antes de sustituir un principal v1 finalizado."""
    anterior = leer(REGISTRO)
    if anterior and anterior["version"] == 1:
        if anterior["estado"] != "finalizada":
            raise ValueError("No se archiva como finalizada una operación pendiente")
        _inmutable(RAIZ / anterior["operacion"] / "finalizada-v1.json", anterior)


def escribir(datos):
    """Publica el registro; las constancias por operación nunca se sobrescriben."""
    if datos.get("version") == 2:
        datos["secuencia"] = secuencia(datos["estado"], datos["paso"], datos["pasos"])
    analizar(datos)
    if datos["version"] == 2:
        directorio = RAIZ / datos["operacion"]
        if datos["estado"] == "iniciada":
            _inmutable(directorio / "inicio.json", datos)
        elif datos["estado"] == "finalizada":
            _inmutable(directorio / "finalizada.json", datos)
    descriptor, nombre = tempfile.mkstemp(prefix=".siged-registro-", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, ensure_ascii=True)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(nombre, REGISTRO)
        if os.name != "nt":
            directorio = os.open(DATA_DIR, os.O_RDONLY)
            try:
                os.fsync(directorio)
            finally:
                os.close(directorio)
    finally:
        Path(nombre).unlink(missing_ok=True)
