"""Validación y creación de avisos institucionales."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import Request, UploadFile

from app.actividad import registrar
from app.archivos import ArchivoInvalido, guardar_en_disco
from app.catalogos import DEPARTAMENTOS
from app.database import conectar
from app.eliminaciones import descartar_generado

logger = logging.getLogger("gestor")
TAMANO_MAXIMO_BANNER = 8 * 1024 * 1024
DURACIONES_AVISO = (1, 3, 7, 15, 30)
MAX_DIAS_AVISO = 3650


def calcular_vencimiento(duracion: str, dias_personalizados: str) -> int | None:
    if duracion == "sin_vencimiento":
        return None
    if duracion == "personalizada":
        if not (1 <= len(dias_personalizados) <= 4
                and dias_personalizados.isascii() and dias_personalizados.isdecimal()):
            raise ValueError("Duración personalizada inválida")
        dias = int(dias_personalizados)
        if not 1 <= dias <= MAX_DIAS_AVISO:
            raise ValueError("Duración personalizada fuera de rango")
    elif duracion in {str(dias) for dias in DURACIONES_AVISO}:
        dias = int(duracion)
    else:
        raise ValueError("Duración inválida")
    return int((datetime.now(UTC) + timedelta(days=dias)).timestamp())


def crear_aviso_servicio(request: Request, titulo: str, cuerpo: str, departamento: str,
                          publicado: int, imagen: UploadFile | None, avisos_dir: Path, *,
                          duracion: str = "sin_vencimiento", dias_personalizados: str = "") -> str:
    titulo = titulo.strip()
    cuerpo = cuerpo.strip()
    if not titulo or len(titulo) > 200 or len(cuerpo) > 5000:
        return "aviso_campos"
    if departamento not in ("", *DEPARTAMENTOS):
        return "aviso_area"
    if publicado not in (0, 1):
        return "aviso_campos"
    try:
        vencimiento = calcular_vencimiento(duracion, dias_personalizados)
    except ValueError:
        return "aviso_duracion"

    imagen_guardada = None
    imagen_nombre = None
    destino_imagen = None
    if imagen and imagen.filename:
        imagen_nombre = Path((imagen.filename or "").replace("\\", "/")).name[:260]
        extension = Path(imagen_nombre).suffix.lower()
        if extension not in {".png", ".jpg", ".jpeg"}:
            return "aviso_imagen_formato"

        imagen_guardada = f"{uuid4().hex}{extension}"
        destino_imagen = avisos_dir / imagen_guardada
        try:
            tamano = guardar_en_disco(imagen, destino_imagen)
        except ArchivoInvalido as exc:
            descartar_generado("aviso", destino_imagen.name)
            codigo = "aviso_imagen_grande" if exc.codigo == "grande" else "aviso_imagen_formato"
            return codigo
        except OSError:
            descartar_generado("aviso", destino_imagen.name)
            logger.exception("No se pudo guardar la imagen del aviso")
            return "aviso_error"

        if tamano > TAMANO_MAXIMO_BANNER:
            descartar_generado("aviso", destino_imagen.name)
            return "aviso_imagen_grande"

        with destino_imagen.open("rb") as archivo_imagen:
            firma = archivo_imagen.read(8)
        es_png = extension == ".png" and firma == b"\x89PNG\r\n\x1a\n"
        es_jpg = extension in {".jpg", ".jpeg"} and firma.startswith(b"\xff\xd8\xff")
        if not (es_png or es_jpg):
            descartar_generado("aviso", destino_imagen.name)
            return "aviso_imagen_formato"

    try:
        with conectar() as conexion:
            resultado = conexion.execute(
                """
                INSERT INTO avisos
                    (titulo, cuerpo, imagen_guardada, imagen_nombre,
                     departamento, autor_id, publicado, vence_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    titulo,
                    cuerpo,
                    imagen_guardada,
                    imagen_nombre,
                    departamento,
                    request.state.usuario["id"],
                    publicado,
                    vencimiento,
                ),
            )
            aviso_id = resultado.lastrowid
            registrar(request, "aviso_crear", entidad="aviso", entidad_id=aviso_id,
                      entidad_nombre=titulo,
                      detalle=f"{'publicado' if publicado else 'oculto'} · área: {departamento or 'todos'}",
                      conexion=conexion)
    except Exception:
        if destino_imagen:
            descartar_generado("aviso", destino_imagen.name)
        logger.exception("No se pudo crear el aviso")
        return "aviso_error"

    return "aviso_creado"
