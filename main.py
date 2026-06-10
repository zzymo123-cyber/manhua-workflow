import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.routes.project import router as project_router
from api.routes.prompts import router as prompts_router
from api.routes.tasks import router as tasks_router
from api.routes.assets import router as assets_router
from api.routes.chat import router as chat_router
from api.routes.settings import router as settings_router
from api import poller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REQUIRED_ENV = ["VIDU_API_KEY", "WETOKEN_API_KEY", "IDEALAB_API_KEY"]


def check_env():
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logger.warning(f"缺少环境变量: {', '.join(missing)}。对应功能将无法使用。")
    return missing


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = check_env()
    if missing:
        logger.warning(f"启动时缺少环境变量: {missing}")
    await poller.start()
    yield
    await poller.stop()


app = FastAPI(lifespan=lifespan)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


# 主页 no-cache
@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(project_router, prefix="/api/project")
app.include_router(prompts_router, prefix="/api/prompts")
app.include_router(tasks_router, prefix="/api/tasks")
app.include_router(assets_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(settings_router, prefix="/api")

app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
