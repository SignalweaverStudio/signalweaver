# SignalWeaver: boot check
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app.routers.ethos import router as ethos_router
from app.api.profiles import router as profiles_router

from app.db import engine
from app.models import Base
from app.api.anchors import router as anchors_router
from app.api.gate import router as gate_router

app = FastAPI(title="SignalWeaver MVP")

# Create tables
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "app": "SignalWeaver MVP",
        "health": "/health",
        "docs": "/docs",
        "tester": "/tester",
    }


@app.get("/tester", response_class=HTMLResponse)
def tester():
    html_path = Path(__file__).with_name("tester.html")
    return html_path.read_text(encoding="utf-8")


# Routers
# Note: your routers already define their own paths (e.g. POST "/")
# so we keep prefixes as they appear in Swagger: /anchors/* and /gate/*
app.include_router(anchors_router, prefix="/anchors", tags=["anchors"])
app.include_router(gate_router, prefix="/gate", tags=["gate"])
app.include_router(profiles_router, prefix="/profiles", tags=["profiles"])

app.include_router(ethos_router, tags=["ethos"])

