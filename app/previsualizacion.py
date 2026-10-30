"""Previsualización de documentos ofimáticos mediante LibreOffice headless."""

from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from uuid import uuid4

from app.database import DATA_DIR


MAXIMO_DESCOMPRIMIDO = 100 * 1024 * 1024
CACHE_LOCAL = Path(os.environ.get("LOCALAPPDATA", str(DATA_DIR / "cache")))
DIRECTORIO_CACHE = CACHE_LOCAL / "SIGED" / "previsualizaciones"
MAXIMO_CACHE_BYTES = 512 * 1024 * 1024
CACHE_MAX_ANTIGUEDAD_SEGUNDOS = 30 * 24 * 60 * 60
VERSION_CACHE = "v1"
_BLOQUEOS_CACHE: dict[str, threading.Lock] = {}
_BLOQUEO_INDICE_CACHE = threading.Lock()

NS_WORD = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class ArchivoNoPrevisualizable(ValueError):
    """El archivo está dañado o su contenido no se puede mostrar con seguridad."""


def localizar_libreoffice() -> str | None:
    """Encuentra soffice usando una ruta configurada, PATH o las rutas de Windows."""
    configurado = os.environ.get("LIBREOFFICE_PATH")
    if configurado and Path(configurado).is_file():
        return configurado

    encontrado = shutil.which("soffice") or shutil.which("soffice.exe")
    if encontrado:
        return encontrado

    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        raiz = os.environ.get(variable)
        if raiz:
            candidato = Path(raiz) / "LibreOffice" / "program" / "soffice.exe"
            if candidato.is_file():
                return str(candidato)
    return None


def _identidad_cache(ruta: Path, ejecutable: str) -> tuple[str, str]:
    extension = ruta.suffix.lower()
    digest = hashlib.sha256()
    try:
        with ruta.open("rb") as archivo:
            for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
                digest.update(bloque)
        marca_libreoffice = Path(ejecutable).stat().st_mtime_ns
    except OSError as exc:
        raise ArchivoNoPrevisualizable("No se pudo leer el archivo para preparar su vista previa.") from exc
    contenido = digest.hexdigest()
    clave = hashlib.sha256(
        f"{VERSION_CACHE}|{extension}|{contenido}|{marca_libreoffice}".encode("utf-8")
    ).hexdigest()
    return clave, f"{extension.lstrip('.')}-{contenido}"


def _limpiar_cache(preservar: Path | None = None) -> None:
    """Elimina las vistas menos recientes cuando el caché excede su límite."""
    try:
        archivos = [p for p in DIRECTORIO_CACHE.glob("*.pdf") if p.is_file()]
        ahora = time.time()
        for archivo in archivos[:]:
            try:
                if ahora - archivo.stat().st_mtime > CACHE_MAX_ANTIGUEDAD_SEGUNDOS:
                    archivo.unlink(missing_ok=True)
                    archivos.remove(archivo)
            except OSError:
                continue
        total = sum(p.stat().st_size for p in archivos)
        if total <= MAXIMO_CACHE_BYTES:
            return
        for archivo in sorted(archivos, key=lambda p: p.stat().st_mtime):
            if preservar is not None and archivo == preservar:
                continue
            try:
                tamano = archivo.stat().st_size
                archivo.unlink(missing_ok=True)
                total -= tamano
                if total <= MAXIMO_CACHE_BYTES * 0.8:
                    break
            except OSError:
                continue
    except OSError:
        return


def convertir_office_a_pdf(ruta: Path) -> tuple[Path, str | None]:
    """Convierte XLSX, DOCX o PPTX y reutiliza el PDF si el original no cambió."""
    ejecutable = localizar_libreoffice()
    if not ejecutable:
        raise ArchivoNoPrevisualizable(
            "No se encontró LibreOffice. Configura LIBREOFFICE_PATH con la ruta de soffice.exe."
        )

    exportadores = {
        ".xlsx": "calc_pdf_Export",
        ".docx": "writer_pdf_Export",
        ".pptx": "impress_pdf_Export",
    }
    limites_segundos = {".xlsx": 60, ".docx": 180, ".pptx": 180}
    exportador = exportadores.get(ruta.suffix.lower())
    if exportador is None:
        raise ArchivoNoPrevisualizable("Este formato no está disponible para vista previa con LibreOffice.")

    DIRECTORIO_CACHE.mkdir(parents=True, exist_ok=True)
    clave, prefijo = _identidad_cache(ruta, ejecutable)
    salida_cache = DIRECTORIO_CACHE / f"{prefijo}-{clave}.pdf"
    with _BLOQUEO_INDICE_CACHE:
        bloqueo = _BLOQUEOS_CACHE.setdefault(clave, threading.Lock())

    with bloqueo:
        if salida_cache.is_file() and salida_cache.stat().st_size > 0:
            os.utime(salida_cache, None)
            return salida_cache, None

        directorio = tempfile.mkdtemp(prefix="gestor-vista-")
        perfil = Path(directorio) / "perfil"
        destino = Path(directorio) / "pdf"
        destino.mkdir()
        salida = destino / f"{ruta.stem}.pdf"
        temporal_cache = salida_cache.with_name(f".{salida_cache.stem}-{uuid4().hex}.tmp")
        comando = [
            ejecutable,
            f"-env:UserInstallation={perfil.as_uri()}",
            "--headless",
            "--convert-to",
            f"pdf:{exportador}",
            "--outdir",
            str(destino),
            str(ruta),
        ]

        try:
            resultado = subprocess.run(
                comando,
                capture_output=True,
                text=True,
                timeout=limites_segundos[ruta.suffix.lower()],
                check=False,
            )
            if resultado.returncode != 0 or not salida.is_file() or salida.stat().st_size == 0:
                raise ArchivoNoPrevisualizable("LibreOffice no pudo generar la vista previa del documento.")
            shutil.copy2(salida, temporal_cache)
            os.replace(temporal_cache, salida_cache)
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(directorio, ignore_errors=True)
            temporal_cache.unlink(missing_ok=True)
            raise ArchivoNoPrevisualizable(
                f"LibreOffice superó el límite de {limites_segundos[ruta.suffix.lower()]} segundos al convertir el archivo. "
                "Intenta de nuevo o revisa si el documento es muy grande o complejo."
            ) from exc
        except ArchivoNoPrevisualizable:
            shutil.rmtree(directorio, ignore_errors=True)
            temporal_cache.unlink(missing_ok=True)
            raise
        except OSError as exc:
            shutil.rmtree(directorio, ignore_errors=True)
            temporal_cache.unlink(missing_ok=True)
            raise ArchivoNoPrevisualizable("No se pudo iniciar LibreOffice o guardar la vista previa.") from exc
        except Exception:
            shutil.rmtree(directorio, ignore_errors=True)
            temporal_cache.unlink(missing_ok=True)
            raise

        shutil.rmtree(directorio, ignore_errors=True)
        _limpiar_cache(salida_cache)
        return salida_cache, None


def convertir_xlsx_a_pdf(ruta: Path) -> tuple[Path, str | None]:
    """Compatibilidad con el nombre usado por versiones anteriores de la app."""
    return convertir_office_a_pdf(ruta)


def _abrir_office(ruta: Path) -> zipfile.ZipFile:
    try:
        archivo = zipfile.ZipFile(ruta)
        if len(archivo.infolist()) > 5000 or sum(
            entrada.file_size for entrada in archivo.infolist()
        ) > MAXIMO_DESCOMPRIMIDO:
            archivo.close()
            raise ArchivoNoPrevisualizable("El contenido comprimido excede el límite de vista previa.")
        return archivo
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchivoNoPrevisualizable("El archivo Office no tiene una estructura válida.") from exc


def leer_docx(ruta: Path) -> list[str]:
    """Devuelve párrafos de Word como texto plano; no interpreta ni ejecuta contenido."""
    with _abrir_office(ruta) as archivo:
        try:
            raiz = ET.fromstring(archivo.read("word/document.xml"))
        except (KeyError, ET.ParseError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
            raise ArchivoNoPrevisualizable("No se pudo leer el contenido del documento Word.") from exc

    parrafos = []
    for parrafo in raiz.findall(".//w:p", NS_WORD):
        texto = "".join(nodo.text or "" for nodo in parrafo.findall(".//w:t", NS_WORD))
        if texto.strip():
            parrafos.append(texto)
    return parrafos
