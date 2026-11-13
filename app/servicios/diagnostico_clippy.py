"""Diagnósticos de solo lectura para la cuenta autenticada."""

from app.acceso_documentos import filtro_area_documento
from app.almacenamiento import consultar_uso_disco
from app.configuracion import STORAGE_DIR
from app.database import conectar
from app.seguridad import PERMISOS
from app.servicios.estado_sistema import consultar_estado_sistema

ACCIONES = {
    "subir": "subir documentos",
    "editar": "editar documentos",
    "descargar": "descargar documentos",
    "papelera": "enviar documentos a Papelera",
    "restaurar": "restaurar documentos",
    "eliminar": "eliminar definitivamente",
    "gestionar_expedientes": "gestionar expedientes",
    "avisos": "administrar avisos",
    "usuarios": "administrar usuarios",
    "actividad": "consultar Actividad",
}


def diagnosticar_documento(usuario, registro):
    if registro is None:
        return "Indica el número de registro interno. Por ejemplo: «¿Por qué no aparece el documento 123?»."
    filtro, parametros = filtro_area_documento(usuario)
    with conectar() as conexion:
        documento = conexion.execute(
            "SELECT nombre_guardado FROM documentos WHERE id = ? AND eliminado_en IS NULL" + filtro,
            (registro, *parametros),
        ).fetchone()
    if documento is None:
        return ("No encontré un documento disponible para tu cuenta con ese registro. "
                "Revisa el número o consulta a Administración.")
    try:
        disponible = (STORAGE_DIR / documento["nombre_guardado"]).is_file()
    except OSError:
        return "El registro es visible para tu cuenta, pero no pude comprobar el archivo."
    if not disponible:
        return "El registro es visible para tu cuenta, pero el archivo no está disponible. Informa a Administración."
    return ("El registro es visible para tu cuenta y el archivo está disponible. "
            "Si sigue fallando, indica qué acción realizaste y el mensaje exacto.")


def diagnosticar_permisos(usuario, accion):
    permisos = PERMISOS.get(usuario["rol"], set())
    if accion is None:
        disponibles = ", ".join(etiqueta for clave, etiqueta in ACCIONES.items() if clave in permisos)
        return f"Tu rol es {usuario['rol_nombre']}. Entre tus permisos están: {disponibles}. El acceso a documentos también depende del área."
    if accion not in permisos:
        return f"Tu rol actual no permite {ACCIONES[accion]}. Si lo necesitas, consulta a Administración."
    return f"Tu rol actual permite {ACCIONES[accion]}. El área y el estado del recurso pueden limitar una operación concreta."


def diagnosticar_estado(sesion, mensajeria, tema):
    if tema == "mensajeria" and not mensajeria:
        return "La interfaz o el servicio de Mensajería no está habilitado en esta instalación."
    codigo, estado = consultar_estado_sistema(sesion, mensajeria)
    if codigo != 200:
        return "No pude comprobar el estado con tu sesión actual. Vuelve a iniciar sesión e inténtalo de nuevo."
    if tema == "mensajeria":
        return {
            "operativo": "Las comprobaciones de Mensajería pasaron. Si una conversación sigue fallando, indica el mensaje de error y la acción.",
            "degradado": "El sistema informa de una incidencia parcial. Revisa el indicador de Inicio para ver el detalle disponible.",
            "critico": "Hay un fallo en un componente esencial. No puedo confirmar que Mensajería funcione correctamente.",
        }[estado["estado"]]
    etiqueta = {"operativo": "Operativo", "degradado": "Funcionamiento degradado", "critico": "Estado crítico"}
    detalle = " ".join(estado["incidencias"])
    return f"Estado del sistema: {etiqueta[estado['estado']]}. {detalle}".strip()


def diagnosticar_almacenamiento():
    uso = consultar_uso_disco(STORAGE_DIR)
    if not uso["disponible"]:
        return "No pude comprobar el almacenamiento documental. Revisa el indicador de Inicio o consulta a Administración."
    return f"Almacenamiento documental: {uso['libre']} libres de {uso['total']} ({uso['porcentaje']} % ocupado)."
