"""Apertura ZIP en lectura con presupuesto; no valida el contenido del respaldo.

El llamador conserva el archivo abierto y debe garantizar que nadie lo escriba
durante la inspección. La comprobación de identidad detecta cambios ordinarios,
pero no constituye una instantánea ni protección frente a un atacante local.
"""
import os
import struct
import time
import zipfile
from contextlib import contextmanager

from app.inventario_restauracion import limite


class LimiteZip(ValueError):
    """La apertura o lectura superó el presupuesto permitido."""


class _LecturaAcotada:
    def __init__(self, archivo, max_lectura, max_total, segundos):
        self._archivo = archivo
        self._max_lectura = max_lectura
        self._max_total = max_total
        self._total = 0
        self._fin = time.monotonic() + segundos

    def _tiempo(self):
        if time.monotonic() > self._fin:
            raise LimiteZip('Tiempo de lectura ZIP agotado')

    def read(self, size=-1):
        self._tiempo()
        if not isinstance(size, int) or size < 0 or size > self._max_lectura:
            raise LimiteZip('Lectura ZIP individual excede el límite')
        if self._total + size > self._max_total:
            raise LimiteZip('Presupuesto de lectura ZIP agotado')
        resultado = self._archivo.read(size)
        self._total += len(resultado)
        self._tiempo()
        return resultado

    def seek(self, offset, whence=0):
        self._tiempo()
        return self._archivo.seek(offset, whence)

    def tell(self):
        self._tiempo()
        return self._archivo.tell()

    def seekable(self):
        return True


def _identidad(archivo):
    info = os.fstat(archivo.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _conteo_declarado(lector):
    """Solo registros de cierre; no interpreta entradas ni descomprime contenido.

    Se acepta un único disco y offsets desde el comienzo del archivo, sin
    envolturas autoextraíbles. No se reserva memoria según los conteos.
    """
    def invalido():
        raise zipfile.BadZipFile('Registros de cierre ZIP contradictorios o incompletos')

    def leer(offset, size):
        if offset < 0 or offset + size > longitud:
            invalido()
        lector.seek(offset)
        data = lector.read(size)
        if len(data) != size:
            invalido()
        return data

    lector.seek(0, 2)
    longitud = lector.tell()
    inicio = max(0, longitud - 65557)
    cola = leer(inicio, longitud - inicio)
    candidatos = []
    pos = cola.find(b'PK\x05\x06')
    while pos >= 0:
        if pos + 22 <= len(cola):
            valores = struct.unpack_from('<4s4H2IH', cola, pos)
            if pos + 22 + valores[-1] == len(cola):
                candidatos.append((inicio + pos, valores))
        pos = cola.find(b'PK\x05\x06', pos + 1)
    if len(candidatos) != 1:
        invalido()
    offset, (_, disco, disco_cd, n_disco, n_total, tam_cd, off_cd, _) = candidatos[0]
    localizador = leer(offset - 20, 20) if offset >= 20 else b''
    if localizador.startswith(b'PK\x06\x07'):
        _, disco64, off64, discos = struct.unpack('<4sIQI', localizador)
        if disco64 != 0 or discos != 1:
            invalido()
        campos = struct.unpack('<4sQ2H2I4Q', leer(off64, 56))
        sig, size, _, _, d64, cd64, nd64, nt64, tam64, cd_off64 = campos
        if (sig != b'PK\x06\x06' or size < 44 or off64 + 12 + size != offset - 20
                or d64 != 0 or cd64 != 0 or nd64 != nt64 or cd_off64 + tam64 != off64):
            invalido()
        for convencional, real, marcador in ((disco, d64, 65535), (disco_cd, cd64, 65535),
                (n_disco, nd64, 65535), (n_total, nt64, 65535),
                (tam_cd, tam64, 0xffffffff), (off_cd, cd_off64, 0xffffffff)):
            if convencional != marcador and convencional != real:
                invalido()
        return nt64
    if (disco != 0 or disco_cd != 0 or n_disco != n_total
            or tam_cd == 0xffffffff or off_cd == 0xffffffff or off_cd + tam_cd != offset):
        invalido()
    return n_total


@contextmanager
def abrir_zip_acotado(archivo):
    """Abre un archivo binario existente, sin reabrir su ruta ni extraer datos.

    Los límites de lectura se aplican antes de cada petición de zipfile, también
    a la lectura del directorio central. El límite de entradas se comprueba tras
    su análisis; el límite previo de bytes acota el tamaño que zipfile analiza.
    """
    max_lectura = limite('GESTOR_ZIP_MAX_LECTURA_BYTES', 8 * 1024**2)
    max_total = limite('GESTOR_ZIP_MAX_LECTURA_TOTAL_BYTES', 1024**4)
    max_entradas = limite('GESTOR_RESPALDO_MAX_ENTRADAS', 100000)
    segundos = limite('GESTOR_ZIP_MAX_SEGUNDOS', 3600)
    antes = _identidad(archivo)
    lector = _LecturaAcotada(archivo, max_lectura, max_total, segundos)
    declarado = _conteo_declarado(lector)
    if declarado > max_entradas:
        raise LimiteZip('Conteo declarado supera el límite de entradas')
    with zipfile.ZipFile(lector, 'r', allowZip64=True) as zip_abierto:
        lector._tiempo()
        if len(zip_abierto.filelist) > max_entradas:
            raise LimiteZip('El ZIP supera el límite de entradas')
        if len(zip_abierto.filelist) != declarado:
            raise zipfile.BadZipFile('Conteo declarado no coincide con las entradas reales')
        # La política existente sigue siendo la fuente de verdad para rutas,
        # duplicados y límites declarados; no inspecciona contenido ni SQLite.
        from app.respaldo import _validar_entradas
        _validar_entradas(zip_abierto.filelist)
        lector._tiempo()
        if _identidad(archivo) != antes:
            raise LimiteZip('El ZIP cambió durante la apertura')
        try:
            yield zip_abierto
        finally:
            if _identidad(archivo) != antes:
                raise LimiteZip('El ZIP cambió durante la inspección')
