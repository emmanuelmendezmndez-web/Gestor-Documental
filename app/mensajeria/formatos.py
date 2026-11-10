"""Validación estructural acotada de adjuntos externos, sin extraer ni renderizar."""

import codecs
import re
import stat
import struct
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import PureWindowsPath
from xml.parsers import expat

from app.apertura_zip_acotada import _conteo_declarado, _LecturaAcotada
from app.tipos_archivo import EXTENSIONES_PERMITIDAS

BLOQUE = 128 * 1024
OFICINA = {
    ".docx": ("word/document.xml", "wordprocessingml.document.main+xml", "wordprocessingml", "document"),
    ".xlsx": ("xl/workbook.xml", "spreadsheetml.sheet.main+xml", "spreadsheetml", "workbook"),
    ".pptx": ("ppt/presentation.xml", "presentationml.presentation.main+xml", "presentationml", "presentation"),
}
NS_CONTENIDO = "{http://schemas.openxmlformats.org/package/2006/content-types}"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _segmento(nombre):
    if (not nombre or nombre in {".", ".."} or nombre.endswith((".", " "))
            or any(x in nombre for x in '<>:"/\\|?*')
            or any(unicodedata.category(x).startswith("C") for x in nombre)):
        return False
    base = nombre.split(".")[0].rstrip().upper()
    return re.fullmatch(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9¹²³])", base) is None


def extension(nombre):
    if (not isinstance(nombre, str) or not 1 <= len(nombre) <= 200
            or not _segmento(nombre) or nombre != nombre.strip() or nombre.count(".") != 1
            or nombre.startswith(".")):
        raise ValueError("nombre_invalido")
    sufijo = PureWindowsPath(nombre).suffix.lower()
    if sufijo not in EXTENSIONES_PERMITIDAS:
        raise ValueError("formato_no_permitido")
    return sufijo


def _exigir(condicion):
    if not condicion:
        raise ValueError("formato_incompatible")


def _leer(archivo, cantidad):
    bloque = archivo.read(cantidad)
    _exigir(len(bloque) == cantidad)
    return bloque


def _txt(archivo, _tamano, comprobar):
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    while bloque := archivo.read(BLOQUE):
        comprobar()
        texto = decoder.decode(bloque)
        _exigir(not any(ord(c) < 32 and c not in "\r\n\t" or 127 <= ord(c) <= 159 for c in texto))
    decoder.decode(b"", final=True)


def _pdf(archivo, tamano, _comprobar):
    _exigir(re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", archivo.read(16)))
    inicio = max(0, tamano - 4096)
    archivo.seek(inicio)
    cierre = re.search(rb"startxref\s+([0-9]{1,12})\s+%%EOF[\x00\t\r\n\f ]*$", archivo.read(4096))
    _exigir(cierre)
    offset = int(cierre[1])
    _exigir(0 < offset < inicio + cierre.start())
    archivo.seek(offset)
    _exigir(re.match(rb"(?:xref\s|[0-9]+\s+[0-9]+\s+obj\b)", archivo.read(64)))


def _png(archivo, tamano, comprobar):
    _exigir(_leer(archivo, 8) == b"\x89PNG\r\n\x1a\n")
    hay_datos = False
    for indice in range(8192):
        comprobar()
        longitud, tipo = struct.unpack(">I4s", _leer(archivo, 8))
        _exigir(longitud <= tamano - archivo.tell() - 4 and re.fullmatch(rb"[A-Za-z]{4}", tipo))
        crc = zlib.crc32(tipo)
        if indice == 0:
            _exigir(tipo == b"IHDR" and longitud == 13)
            datos = _leer(archivo, longitud)
            ancho, alto, profundidad, color, compresion, filtro, entrelazado = struct.unpack(">IIBBBBB", datos)
            _exigir(0 < ancho * alto <= 64_000_000 and profundidad in {
                0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16),
            }.get(color, ()) and compresion == filtro == 0 and entrelazado in (0, 1))
            crc = zlib.crc32(datos, crc)
        else:
            _exigir(tipo != b"IHDR")
            if tipo == b"IDAT" and longitud:
                hay_datos = True
            pendiente = longitud
            while pendiente:
                comprobar()
                datos = _leer(archivo, min(pendiente, BLOQUE))
                crc = zlib.crc32(datos, crc)
                pendiente -= len(datos)
        _exigir(struct.unpack(">I", _leer(archivo, 4))[0] == crc)
        if tipo == b"IEND":
            _exigir(hay_datos and not longitud and archivo.tell() == tamano)
            return
    _exigir(False)


def _jpg(archivo, tamano, comprobar):
    _exigir(_leer(archivo, 2) == b"\xff\xd8")
    dimensiones = False
    for _ in range(8192):
        comprobar()
        _exigir(_leer(archivo, 1) == b"\xff")
        marcador = _leer(archivo, 1)[0]
        if marcador == 255:
            archivo.seek(-1, 1)
            continue
        _exigir(marcador == 0xDA or 0xC0 <= marcador <= 0xFE and marcador not in range(0xD0, 0xD9 + 1))
        longitud = int.from_bytes(_leer(archivo, 2), "big") - 2
        _exigir(0 <= longitud <= tamano - archivo.tell() - 2)
        if marcador in (0xC0, 0xC1, 0xC2):
            _exigir(not dimensiones and longitud >= 6)
            datos = _leer(archivo, 6)
            _, alto, ancho, canales = struct.unpack(">BHHB", datos)
            _exigir(0 < ancho * alto <= 64_000_000 and canales in (1, 3, 4) and longitud == 6 + 3 * canales)
            dimensiones = True
            longitud -= 6
        archivo.seek(longitud, 1)
        if marcador == 0xDA:
            _exigir(dimensiones and longitud >= 6 and archivo.tell() < tamano - 2)
            archivo.seek(-2, 2)
            _exigir(_leer(archivo, 2) == b"\xff\xd9")
            return
    _exigir(False)


def _xml_seguro(raices, al_elemento):
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.StartDoctypeDeclHandler = lambda *_: _exigir(False)
    iniciado = False

    def inicio(nombre, atributos):
        nonlocal iniciado
        if not iniciado:
            _exigir(nombre in raices)
            iniciado = True
        al_elemento(nombre, atributos)

    parser.StartElementHandler = inicio
    return parser


def _oficina(archivo, sufijo, comprobar):
    lector = _LecturaAcotada(archivo, 1024**2, 32 * 1024**2, 30)
    declarado = _conteo_declarado(lector)
    _exigir(0 < declarado <= 2048)
    principal, tipo_esperado, namespace, raiz = OFICINA[sufijo]
    verificados = set()
    archivos = set()
    tipos = None
    objetivos = []
    total = 0

    def relacion(nombre, atributos):
        if nombre == NS_REL + " Relationship" and atributos.get("Type", "").endswith("/officeDocument"):
            objetivos.append((atributos.get("Target", "").removeprefix("/"),
                              atributos.get("TargetMode", "Internal")))

    with zipfile.ZipFile(lector) as paquete:
        _exigir(len(paquete.filelist) == declarado)
        for info in paquete.filelist:
            comprobar()
            nombre = info.orig_filename
            canonico = nombre.rstrip("/").casefold()
            partes = nombre.removesuffix("/").split("/")
            _exigir(len(nombre) <= 260 and all(_segmento(p) for p in partes)
                    and canonico not in verificados and nombre == info.filename
                    and not (info.flag_bits & 1 or info.external_attr & 0x400)
                    and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR)
                    and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    and not canonico.endswith(("vbaproject.bin", ".exe", ".dll", ".js", ".vbs", ".ps1", ".msi"))
                    and info.file_size <= 24 * 1024**2 and (not info.is_dir() or not info.file_size))
            verificados.add(canonico)
            if not info.is_dir():
                archivos.add(canonico)
            if nombre in {"_rels/.rels", principal}:
                _exigir(info.file_size > 0)
            parser = None
            if nombre == "_rels/.rels":
                _exigir(info.file_size <= 256 * 1024)
                parser = _xml_seguro({NS_REL + " Relationships"}, relacion)
            elif nombre == principal:
                parser = _xml_seguro({
                    f"http://schemas.openxmlformats.org/{namespace}/2006/main {raiz}",
                    f"http://purl.oclc.org/ooxml/{namespace}/main {raiz}",
                }, lambda *_: None)
            with paquete.open(info) as entrada:
                leidos = 0
                xml = bytearray()
                if nombre == "[Content_Types].xml":
                    _exigir(info.file_size <= 256 * 1024)
                while bloque := entrada.read(BLOQUE):
                    comprobar()
                    leidos += len(bloque)
                    total += len(bloque)
                    _exigir(leidos <= info.file_size and total <= 64 * 1024**2)
                    if nombre == "[Content_Types].xml":
                        xml.extend(bloque)
                    if parser is not None:
                        parser.Parse(bloque, False)
                _exigir(leidos == info.file_size)
                if parser is not None:
                    parser.Parse(b"", True)
                if nombre == "[Content_Types].xml":
                    texto = xml.decode("utf-8-sig")
                    _exigir("<!" not in texto)
                    tipos = ET.fromstring(texto)
        _exigir(tipos is not None and tipos.tag == NS_CONTENIDO + "Types"
                and {"_rels/.rels", principal} <= archivos and objetivos == [(principal, "Internal")])
        for nombre in verificados:
            partes = nombre.split("/")
            _exigir(not any("/".join(partes[:i]) in archivos for i in range(1, len(partes))))
        declaraciones = [e.get("ContentType") for e in tipos.findall(NS_CONTENIDO + "Override")
                         if e.get("PartName") == "/" + principal]
        _exigir(declaraciones == ["application/vnd.openxmlformats-officedocument." + tipo_esperado])


def validar(archivo, sufijo, tamano, comprobar):
    archivo.seek(0)
    try:
        if sufijo in OFICINA:
            _oficina(archivo, sufijo, comprobar)
        else:
            validadores = {".txt": _txt, ".pdf": _pdf, ".png": _png, ".jpg": _jpg, ".jpeg": _jpg}
            validadores[sufijo](archivo, tamano, comprobar)
    except (ValueError, ET.ParseError, expat.ExpatError, zipfile.BadZipFile, RuntimeError,
            EOFError, struct.error, zlib.error) as error:
        raise ValueError("formato_incompatible") from error
