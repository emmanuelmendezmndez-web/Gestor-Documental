"""Opciones de orden utilizadas por la biblioteca."""

# Fecha "efectiva" de un documento: la fecha del oficio y, si no se indicó,
# la fecha en que se registró. Así los documentos antiguos también se ordenan y filtran.
EXPR_FECHA = "COALESCE(NULLIF(fecha_documento, ''), date(fecha_subida, 'localtime'))"

# Extensión del archivo (lo que va después del último punto), para ordenar por tipo
EXPR_EXTENSION = (
    "lower(substr(nombre_archivo, "
    "length(rtrim(nombre_archivo, replace(nombre_archivo, '.', ''))) + 1))"
)

# Ordenamientos disponibles. Lo que llega por la URL solo se usa como clave de este
# diccionario; nunca se inserta directamente en la consulta.
ORDENES = {
    "reciente": ("Recién subidos", "id DESC"),
    "fecha_desc": ("Fecha del documento (más recientes)", f"{EXPR_FECHA} DESC, id DESC"),
    "fecha_asc": ("Fecha del documento (más antiguos)", f"{EXPR_FECHA} ASC, id ASC"),
    "titulo_asc": ("Título (A-Z)", "normalizar(titulo) ASC, id DESC"),
    "titulo_desc": ("Título (Z-A)", "normalizar(titulo) DESC, id DESC"),
    "categoria": ("Categoría", "normalizar(categoria) ASC, normalizar(titulo) ASC"),
    "tipo": ("Tipo de archivo", f"{EXPR_EXTENSION} ASC, normalizar(titulo) ASC"),
}
ORDEN_PREDETERMINADO = "reciente"
