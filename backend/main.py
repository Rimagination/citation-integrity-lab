from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    MetadataVerifyRequest,
    ParseRequest,
    ParseResult,
    SupportVerifyRequest,
)
from .parser import parse_text
from .verification import analyze_text, evaluate_support, verify_references


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="Citation Deep Verifier",
    version="0.1.0",
    description="AI 生成文本引文深度核查工具",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="frontend entry not found")
    return FileResponse(index_file)


@app.post("/api/parse", response_model=ParseResult)
async def parse_endpoint(payload: ParseRequest) -> ParseResult:
    try:
        return parse_text(payload.text, mode=payload.mode)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"parse failed: {exc}") from exc


@app.post("/api/verify/metadata")
async def verify_metadata_endpoint(payload: MetadataVerifyRequest) -> dict:
    try:
        results = await verify_references(payload.references)
        return {"reference_results": results}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"metadata verify failed: {exc}") from exc


@app.post("/api/verify/support")
async def verify_support_endpoint(payload: SupportVerifyRequest) -> dict:
    try:
        support = evaluate_support(payload.claim, payload.abstract)
        return {"support": support}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"support verify failed: {exc}") from exc


@app.post("/api/analyze")
async def analyze_endpoint(payload: ParseRequest) -> dict:
    try:
        result = await analyze_text(payload.text, mode=payload.mode)
        return result.model_dump()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"analyze failed: {exc}") from exc
