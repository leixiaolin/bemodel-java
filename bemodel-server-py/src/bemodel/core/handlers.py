from datetime import datetime, timezone
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from .exceptions import BizException
from .result import error


def install_handlers(app):
    @app.exception_handler(BizException)
    async def business(request, exc):
        return JSONResponse(error(str(exc)))

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(Exception)
    async def unknown(request, exc):
        return JSONResponse(error("系统异常: " + str(exc)))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if exc.status_code == 404:
            return JSONResponse({"timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "status": 404, "error": "Not Found", "path": request.url.path}, status_code=404)
        return JSONResponse(error("系统异常: " + str(exc.detail)))
