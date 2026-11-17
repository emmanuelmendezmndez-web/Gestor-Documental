"""Traduce menciones a propuestas de lectura. No consulta ni escribe datos."""

import re
from datetime import date

from app.catalogos import DEPARTAMENTOS
from app.servicios.clippy_extraccion import normalizar

_MUTACION = re.compile(
    r"\b(?:cambia|cambiale|edita|modifica|actualiza|elimina|borra|restaura|recupera|vincula|"
    r"desvincula|sube|publica|archiva|guarda|desactiva|activa|renombra|reemplaza|quita|crea)\b"
)
_ID = re.compile(r"[1-9]\d{0,17}", re.ASCII)
_FOLIO = re.compile(r"[A-Z0-9][A-Z0-9/-]{0,59}", re.ASCII)


def preparar_propuestas(texto, menciones, usuario):
    """Devuelve parámetros para que el usuario decida si quiere usarlos."""
    if not isinstance(menciones, dict):
        return None
    avisos = []
    criterios = {}
    enlaces = []
    consumir = {}
    if menciones["negaciones"]:
        return {"avisos": ["negacion"], "criterios": {}, "enlaces": []}
    if _MUTACION.search(normalizar(texto)):
        return {"avisos": ["solo_lectura"], "criterios": {}, "enlaces": []}

    folios = {r["valor"] for r in menciones["folios"] if _FOLIO.fullmatch(r["valor"])}
    marcas = menciones["folios"]
    if len(folios) == 1:
        folio = next(iter(folios))
        antecedente = normalizar(texto[:marcas[0]["inicio"]])
        if folio.startswith("OF-") or re.search(r"\boficio(?:\s+(?:numero|num\.?|no\.?))?\s*[:#]?\s*$", antecedente):
            criterios["oficio"] = folio
            consumir["oficio"] = marcas[0]["texto"]
        else:
            enlaces.append({"tipo": "folio", "valor": folio})
    elif len(folios) > 1:
        avisos.append("folios_varios")

    areas = {r["valor"] for r in menciones["departamentos"]}
    permitidas = set(DEPARTAMENTOS) if usuario["rol"] == "admin" else {usuario.get("departamento")}
    validas = areas & permitidas & set(DEPARTAMENTOS)
    if len(areas) == 1 and validas:
        criterios["departamento"] = next(iter(validas))
        consumir["departamento"] = menciones["departamentos"][0]["texto"]
    elif areas:
        avisos.append("areas_varias" if areas <= permitidas else "area_no_disponible")

    referencias = {r["valor"] for r in menciones["referencias"]}
    if len(referencias) == 1:
        clase, _, valor = next(iter(referencias)).partition(":")
        if clase == "registro" and _ID.fullmatch(valor):
            enlaces.append({"tipo": "registro", "valor": valor})
        if clase == "titulo" and 1 <= len(valor) <= 90:
            enlaces.append({"tipo": "titulo", "valor": valor})
    elif len(referencias) > 1:
        avisos.append("referencias_varias")

    fechas = menciones["fechas"]
    if len(fechas) > 1:
        avisos.append("fechas_varias")
    elif fechas:
        fecha = fechas[0]
        if fecha["estado"] == "exacta":
            valor = date.fromisoformat(fecha["valor"]).isoformat()
            criterios.update(desde=valor, hasta=valor)
            consumir["desde"] = fecha["texto"]
        elif fecha["estado"] in {"ambigua", "invalida"}:
            avisos.append("fecha_ambigua")
        elif fecha["estado"] == "relativa" and normalizar(fecha["texto"]) in {"antier", "anteayer"}:
            consumir["desde"] = fecha["texto"]
            return {"avisos": avisos, "criterios": criterios, "enlaces": enlaces,
                    "consumir": consumir, "dias_relativos": -2}
        elif fecha["estado"] in {"sin_anio", "mes"}:
            avisos.append("fecha_incompleta")
    return {"avisos": avisos, "criterios": criterios, "enlaces": enlaces, "consumir": consumir}

