from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import DEFAULT_PLATFORMS, MAX_UPLOAD_MB, OPTIONAL_PLATFORMS, OUTPUT_ROOT, SUPPORTED_IMAGE_TYPES
from .crawler import collect_candidates
from .models import ProductFacts
from .query import generate_queries
from .storage import create_run, load_manifest


app = FastAPI(title="Shoe Image Sourcing Tool")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
Path("outputs").mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return {"message": "Shoe Image Sourcing Tool"}
    return FileResponse(index_path)


@app.get("/api/platforms")
def platforms():
    return {
        "default": [platform.model_dump() for platform in DEFAULT_PLATFORMS],
        "optional": [platform.model_dump() for platform in OPTIONAL_PLATFORMS],
    }


@app.post("/api/runs")
async def create_crawl_run(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    brand: str | None = Form(None),
    model: str | None = Form(None),
    sku: str | None = Form(None),
    color: str | None = Form(None),
    keywords: str | None = Form(None),
    platforms: str = Form("wildberries,yandex_images,ozon,ebay,official"),
):
    if image.content_type not in SUPPORTED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, and WebP images are supported")

    facts = ProductFacts(brand=brand, model=model, sku=sku, color=color, keywords=keywords)
    selected_platforms = [item.strip() for item in platforms.split(",") if item.strip()]
    queries = generate_queries(facts)
    manifest, run_dir = create_run(facts, queries, selected_platforms, OUTPUT_ROOT)

    input_path = run_dir / "input" / (image.filename or "upload")
    bytes_written = 0
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    with input_path.open("wb") as handle:
        while chunk := await image.read(1024 * 1024):
            bytes_written += len(chunk)
            if bytes_written > max_bytes:
                raise HTTPException(status_code=413, detail=f"Upload exceeds {MAX_UPLOAD_MB} MB")
            handle.write(chunk)

    background_tasks.add_task(collect_candidates, manifest, run_dir)
    return {"run_id": manifest.run_id, "status": manifest.status, "queries": queries}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run_dir = OUTPUT_ROOT / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return load_manifest(run_dir).model_dump()
