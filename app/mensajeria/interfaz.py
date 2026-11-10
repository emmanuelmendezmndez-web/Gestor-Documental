"""Vista experimental de Mensajería y selección documental autorizada."""

from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse

from app.database import normalizar_texto
from app.mensajeria import biblioteca, formatos, motor, sesiones_ws
from app.mensajeria.api_http import PATRON_REF, PRIVADAS, _credencial, _ejecutar, _error
from app.mensajeria.websocket import _origen_exacto
from app.plantillas import templates
from app.seguridad import requiere_permiso
from app.utilidades import escapar_like

_POR_PAGINA = 20


def _documentos(actor, destinatario, buscar, despues):
    if actor == destinatario:
        raise motor.ErrorMotor(biblioteca.NO_DISPONIBLE)
    with motor._transaccion(actor, destinatario) as (principal, _, _, _, _):
        alcance, parametros, descarga = biblioteca._alcance(principal, (actor, destinatario))
        if not descarga:
            return [], None, False
        termino = "%" + escapar_like(normalizar_texto(buscar.strip())) + "%"
        filas = principal.execute(
            r"""SELECT mensajeria_ref, titulo, nombre_archivo FROM documentos
               WHERE eliminado_en IS NULL AND mensajeria_ref>? AND mensajeria_original=nombre_guardado
               AND (normalizar(titulo) LIKE ? ESCAPE '\' OR normalizar(nombre_archivo) LIKE ? ESCAPE '\')"""
            + alcance + " ORDER BY mensajeria_ref LIMIT ?",
            (despues or "", termino, termino, *parametros, _POR_PAGINA + 1),
        ).fetchall()
        siguiente = filas[_POR_PAGINA - 1][0] if len(filas) > _POR_PAGINA else None
        documentos = [fila for fila in filas[:_POR_PAGINA]
                      if len(fila["nombre_archivo"] or "") <= 260 and formatos._segmento(fila["nombre_archivo"])]
        return documentos, siguiente, True


def instalar(app, *, origenes, https_only):
    if not getattr(app.state, "mensajeria_http_instalada", False):
        raise ValueError("La interfaz requiere la API experimental")
    permitidos = {_origen_exacto(origen) for origen in origenes}
    app.state.mensajeria_interfaz = True

    @app.get("/mensajeria", response_class=HTMLResponse, include_in_schema=False,
             dependencies=[Depends(requiere_permiso("ver"))])
    async def mensajes(
        request: Request,
        destinatario: Annotated[str | None, Query(pattern=PATRON_REF)] = None,
        buscar: Annotated[str, Query(max_length=120)] = "",
        despues: Annotated[str | None, Query(pattern=PATRON_REF)] = None,
    ):
        if destinatario is None:
            return templates.TemplateResponse(
                request=request, name="mensajeria.html", context={"pagina": "mensajeria"}, headers=PRIVADAS,
            )
        try:
            credencial = _credencial(request, permitidos, https_only)
            documentos, siguiente, descarga = await _ejecutar(
                credencial, _documentos, destinatario, buscar, despues, lectura=True,
            )
        except sesiones_ws.ERRORES_DATOS as error:
            return _error(error)
        return templates.TemplateResponse(
            request=request, name="_mensajeria_documentos.html", headers=PRIVADAS,
            context={"documentos": documentos, "siguiente": siguiente, "descarga": descarga},
        )
