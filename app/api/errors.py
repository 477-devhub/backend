"""HACKATHON-DAY: stable errors without echoed request bodies or secrets."""
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse

CODES = {400:"invalid_request", 403:"forbidden", 404:"not_found", 405:"method_not_allowed", 409:"conflict",
         413:"media_too_large", 422:"validation_error", 503:"media_unavailable"}

def register_errors(app):
    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        message = str(exc.detail)
        return JSONResponse(status_code=exc.status_code,
            content={"detail":exc.detail, "error":{"code":CODES.get(exc.status_code,"http_error"),
                     "message":message, "fields":[]}}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [{"loc":list(e["loc"]), "type":e["type"], "msg":e["msg"]}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail":fields,
            "error":{"code":"validation_error", "message":"Request validation failed", "fields":fields}})

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse(status_code=500, content={"detail":"Internal server error",
            "error":{"code":"internal_error", "message":"Internal server error", "fields":[]}})
