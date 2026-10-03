"""One ASGI app, one port: the MCP server (/mcp + its OAuth endpoints) in front, the web UI's
REST API (/api) and the built single-page app behind it."""

from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Mount

from app import api, config
from app.mcp_server import mcp

web = FastAPI(title="Sales Pipeline", docs_url=None, redoc_url=None, openapi_url=None)
api.register_errors(web)
web.include_router(api.router)


@web.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


if (config.WEB_DIST / "assets").is_dir():
    web.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")


@web.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    file = (config.WEB_DIST / path).resolve()
    if path and file.is_file() and config.WEB_DIST.resolve() in file.parents:
        return FileResponse(file)
    index = config.WEB_DIST / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "Web UI not built — run `npm run build` in web/."}, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


public_host = urlsplit(config.BASE_URL).netloc
app = mcp.streamable_http_app(
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[config.BASE_URL, "http://127.0.0.1:*", "http://localhost:*"],
    ),
)
# MCP + OAuth routes match first; everything else goes to the web app.
app.router.routes.append(Mount("/", app=web))
