from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pathlib import Path
from fastapi import Depends, Request
from app.security import verify_api_key, rate_limit

def _rl(request: Request):
    rate_limit(request, limit=60, window_s=60)

router = APIRouter(
    dependencies=[Depends(verify_api_key), Depends(_rl)],
)




@router.get("/ethos", response_class=PlainTextResponse, summary="Return SignalWeaver ethos invariants")
def get_ethos():
    candidates = [
        Path(__file__).resolve().parents[4] / "ETHOS.md",
        Path(__file__).resolve().parents[3] / "ETHOS.md",
        Path.cwd() / "ETHOS.md",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8")
    return "ETHOS.md not found"
