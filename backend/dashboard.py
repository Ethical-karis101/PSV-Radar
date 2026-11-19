from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.main import app

DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "frontend-react" / "dist" / "index.html"
DASHBOARD_DIR = DASHBOARD_PATH.parent


class SPAStaticFiles(StaticFiles):
    """Serve built assets, falling back to index.html for client-side routes
    such as /login and /register. Missing files with an extension stay 404."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in Path(path).name:
                return await super().get_response("index.html", scope)
            raise


# Mount after API routes so browser routes and built assets fall through to the
# React SPA without intercepting API endpoints.
app.mount("/", SPAStaticFiles(directory=DASHBOARD_DIR, html=True, check_dir=False), name="frontend")
