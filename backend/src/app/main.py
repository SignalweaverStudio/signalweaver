from app.api.gate import router as gate_router

from fastapi import FastAPI

from app.db import engine
from app.models import Base
from app.api.anchors import router as anchors_router

app = FastAPI(title="SignalWeaver MVP")

# Create tables
Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(anchors_router, prefix="/anchors", tags=["anchors"])
app.include_router(gate_router, prefix="/gate", tags=["gate"])
