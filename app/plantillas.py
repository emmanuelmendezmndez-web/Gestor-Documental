from fastapi.templating import Jinja2Templates

from app.configuracion import APP_DIR
from app.seguridad import contexto_usuario
from app.catalogos import CATEGORIAS, DEPARTAMENTOS

templates = Jinja2Templates(
    directory=APP_DIR / "templates",
    context_processors=[contexto_usuario],
)
templates.env.globals.update(asistente_categorias=CATEGORIAS, asistente_areas=DEPARTAMENTOS)
