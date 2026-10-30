"""Consultas de búsqueda global y panel de control."""

from pathlib import Path

from app.acceso_documentos import condicion_area_documento, filtro_area_documento
from app.almacenamiento import consultar_uso_disco
from app.database import conectar, normalizar_texto
from app.seguridad import PERMISOS
from app.utilidades import escapar_like


def buscar_global_datos(usuario: dict, q: str) -> dict:
    consulta = q.strip()[:200]
    palabras = normalizar_texto(consulta).split()[:8]
    documentos = []
    expedientes = []

    if palabras:
        condiciones_documentos = ["eliminado_en IS NULL"]
        parametros_documentos = []
        condicion_area, parametros_area = condicion_area_documento(usuario)
        if condicion_area:
            condiciones_documentos.append(condicion_area)
            parametros_documentos.extend(parametros_area)
        for palabra in palabras:
            termino = f"%{escapar_like(palabra)}%"
            condiciones_documentos.append(
                "(normalizar(titulo) LIKE ? ESCAPE '\\' "
                "OR normalizar(nombre_archivo) LIKE ? ESCAPE '\\' "
                "OR normalizar(descripcion) LIKE ? ESCAPE '\\' "
                "OR normalizar(numero_oficio) LIKE ? ESCAPE '\\' "
                "OR CAST(id AS TEXT) LIKE ? ESCAPE '\\')"
            )
            parametros_documentos.extend([termino] * 5)

        where_documentos = " AND ".join(condiciones_documentos)
        with conectar() as conexion:
            documentos = conexion.execute(
                f"""
                SELECT id, titulo, nombre_archivo, categoria, numero_oficio, departamento
                FROM documentos
                WHERE {where_documentos}
                ORDER BY id DESC
                LIMIT 10
                """,
                parametros_documentos,
            ).fetchall()

            if "ver_expedientes" in PERMISOS.get(usuario["rol"], set()):
                condiciones_expedientes = []
                parametros_expedientes = []
                for palabra in palabras:
                    termino = f"%{escapar_like(palabra)}%"
                    condiciones_expedientes.append(
                        "(normalizar(folio) LIKE ? ESCAPE '\\' "
                        "OR normalizar(titulo) LIKE ? ESCAPE '\\' "
                        "OR normalizar(descripcion) LIKE ? ESCAPE '\\')"
                    )
                    parametros_expedientes.extend([termino] * 3)
                expedientes = conexion.execute(
                    """
                    SELECT id, folio, titulo
                    FROM expedientes
                    WHERE """ + " AND ".join(condiciones_expedientes) + """
                    ORDER BY id DESC
                    LIMIT 10
                    """,
                    parametros_expedientes,
                ).fetchall()

    return {
            "titulo": "Búsqueda global",
            "pagina": "buscar",
            "busqueda_global": consulta,
            "documentos_encontrados": documentos,
            "expedientes_encontrados": expedientes,
            "buscar_vacio": not bool(palabras),
    }


def dashboard_datos(usuario: dict, storage_dir: Path) -> dict:
    filtro_area, parametros_area = filtro_area_documento(usuario)
    almacenamiento = consultar_uso_disco(storage_dir)
    with conectar() as conexion:
        total_documentos = conexion.execute(
            "SELECT COUNT(*) AS total FROM documentos WHERE eliminado_en IS NULL" + filtro_area,
            parametros_area,
        ).fetchone()["total"]
        documentos_30_dias = conexion.execute(
            """SELECT COUNT(*) AS total FROM documentos
            WHERE eliminado_en IS NULL
              AND fecha_subida >= datetime('now', '-30 days')""" + filtro_area,
            parametros_area,
        ).fetchone()["total"]
        total_expedientes = conexion.execute(
            "SELECT COUNT(*) AS total FROM expedientes"
        ).fetchone()["total"]
        documentos_en_papelera = conexion.execute(
            "SELECT COUNT(*) AS total FROM documentos WHERE eliminado_en IS NOT NULL"
        ).fetchone()["total"]
        filas_categorias = conexion.execute(
            """SELECT categoria, COUNT(*) AS total
            FROM documentos
            WHERE eliminado_en IS NULL""" + filtro_area + """
            GROUP BY categoria
            ORDER BY total DESC, normalizar(categoria)""",
            parametros_area,
        ).fetchall()
        ultimos_documentos = conexion.execute(
            """SELECT id, titulo, nombre_archivo, categoria,
                   datetime(fecha_subida, 'localtime') AS fecha_subida
            FROM documentos
            WHERE eliminado_en IS NULL""" + filtro_area + """
            ORDER BY fecha_subida DESC, id DESC
            LIMIT 5""",
            parametros_area,
        ).fetchall()
        avisos = conexion.execute(
            """
            SELECT a.id, a.titulo, a.cuerpo, a.imagen_guardada,
                   a.imagen_nombre, a.departamento,
                   datetime(a.fecha_creacion, 'localtime') AS fecha_creacion,
                   COALESCE(u.nombre, u.usuario, 'Administrador') AS autor
            FROM avisos a
            LEFT JOIN usuarios u ON u.id = a.autor_id
            WHERE a.publicado = 1
              AND (a.departamento = '' OR a.departamento = ?)
            ORDER BY a.fecha_creacion DESC, a.id DESC
            LIMIT 10
            """,
            (usuario.get("departamento", ""),),
        ).fetchall()

    distribucion = [
        {
            "categoria": fila["categoria"],
            "total": fila["total"],
            "porcentaje": round((fila["total"] / total_documentos) * 100)
            if total_documentos
            else 0,
        }
        for fila in filas_categorias
    ]

    return {
            "titulo": "Gestor Documental",
            "pagina": "inicio",
            "total_documentos": total_documentos,
            "documentos_30_dias": documentos_30_dias,
            "total_expedientes": total_expedientes,
            "documentos_en_papelera": documentos_en_papelera,
            "almacenamiento": almacenamiento,
            "distribucion": distribucion,
            "ultimos_documentos": ultimos_documentos,
            "avisos": avisos,
    }
