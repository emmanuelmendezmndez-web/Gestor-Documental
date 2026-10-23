from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.seguridad import contexto_usuario

APP_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=APP_DIR / "templates",
    context_processors=[contexto_usuario],
)