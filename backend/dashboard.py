from pathlib import Path

from fastapi.responses import FileResponse

from backend.main import app

DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD_PATH, media_type="text/html")
