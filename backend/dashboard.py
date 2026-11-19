from pathlib import Path
from fastapi.staticfiles import StaticFiles

from backend.main import app

DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "frontend-react" / "dist" / "index.html"
DASHBOARD_DIR = DASHBOARD_PATH.parent

# Mount after API routes so browser routes and built assets fall through to the
# React SPA without intercepting API endpoints.
app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True, check_dir=False), name="frontend")
