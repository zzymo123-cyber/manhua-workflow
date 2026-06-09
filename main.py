import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from api.routes.project import router as project_router
from api.routes.prompts import router as prompts_router
from api.routes.tasks import router as tasks_router
from api.routes.assets import router as assets_router
from api.routes.chat import router as chat_router
from api.routes.settings import router as settings_router
from api.routes.settings import get_api_key
from api import poller
from api.pipeline import ProjectFileError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REQUIRED_ENV = ["VIDU_API_KEY", "WETOKEN_API_KEY", "IDEALAB_API_KEY"]


def get_configured_port() -> int:
    raw_port = os.environ.get("MANHUA_PORT", "8002").strip()
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError("MANHUA_PORT 必须是 1-65535 的整数")
    if not 1 <= port <= 65535:
        raise ValueError("MANHUA_PORT 必须在 1-65535 之间")
    return port


def check_env():
    missing = [k for k in REQUIRED_ENV if not get_api_key(k)]
    if missing:
        logger.warning(f"缺少 API Key: {', '.join(missing)}。对应功能将无法使用。")
    return missing


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = check_env()
    if missing:
        logger.warning(f"启动时缺少 API Key: {missing}")
    await poller.start()
    yield
    await poller.stop()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(ProjectFileError)
async def project_file_error_handler(request: Request, exc: ProjectFileError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


app.include_router(project_router, prefix="/api/project")
app.include_router(prompts_router, prefix="/api/prompts")
app.include_router(tasks_router, prefix="/api/tasks")
app.include_router(assets_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(settings_router, prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "manhua-workflow"}


if __name__ == "__main__":
    import uvicorn
    try:
        port = get_configured_port()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
