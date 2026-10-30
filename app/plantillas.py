from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.seguridad import contexto_usuario
from app.catalogos import CATEGORIAS, DEPARTAMENTOS

APP_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=APP_DIR / "templates",
    context_processors=[contexto_usuario],
)
templates.env.globals.update(asistente_categorias=CATEGORIAS, asistente_areas=DEPARTAMENTOS)
