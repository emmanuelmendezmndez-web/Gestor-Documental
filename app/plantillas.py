from fastapi.templating import Jinja2Templates

from app.catalogos import CATEGORIAS, DEPARTAMENTOS
from app.configuracion import APP_DIR
from app.csrf import token_csrf
from app.seguridad import contexto_usuario

templates = Jinja2Templates(
    directory=APP_DIR / "templates",
    context_processors=[contexto_usuario, lambda request: {"csrf_token": token_csrf(request)}],
)
templates.env.globals.update(asistente_categorias=CATEGORIAS, asistente_areas=DEPARTAMENTOS)
