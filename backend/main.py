from fastapi import FastAPI

app = FastAPI(title="PSV-Radar")


@app.get("/health")
def health():
    return {"status": "ok"}
