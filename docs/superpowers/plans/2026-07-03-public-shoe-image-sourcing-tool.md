# Public Shoe Image Sourcing Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a GitHub-deployable public web app that accepts a shoe image/product facts, searches supported ecommerce/image platforms, downloads candidate images, deduplicates them, converts selected images to 3:4, and exposes results in a browser UI.

**Architecture:** Use a FastAPI backend with modular platform adapters and a simple static frontend served by the backend for the MVP. Crawl jobs run in-process with per-run folders under `outputs/shoe_image_sourcing/runs`; the interfaces leave room for Redis/object storage later. Image processing and dedupe are isolated from crawler adapters.

**Tech Stack:** Python, FastAPI, Uvicorn, HTTPX, Playwright optional adapter hooks, Pillow, imagehash, pytest, vanilla HTML/CSS/JS.

## Global Constraints

- Deployable from GitHub as a public web app.
- First version does not integrate with ERP.
- Default enabled platforms: WB, Yandex Images, Ozon, eBay, brand official site/search, Lamoda, Avito, StockX, GOAT.
- Optional disabled platforms: Amazon, AliExpress, Farfetch, Мегамаркет, KazanExpress / Магнит Маркет.
- Ozon images are marked `competitor_reference_only` by default.
- Selected images export as 3:4 copies while originals are preserved.
- No login-required scraping.
- No得物 App automation.
- No iPhone automation.
- Public-use safeguards: upload size limits, image count limits, per-run cleanup-ready storage, no permanent user upload storage by default.

---

## File Structure

- `shoe_image_sourcing/app.py`: FastAPI app, routes, static serving.
- `shoe_image_sourcing/models.py`: dataclasses/Pydantic models for jobs, product facts, image candidates.
- `shoe_image_sourcing/config.py`: platform defaults, limits, output paths.
- `shoe_image_sourcing/query.py`: English/Russian query generation.
- `shoe_image_sourcing/storage.py`: run folder creation, manifest read/write, file paths.
- `shoe_image_sourcing/image_processing.py`: image validation, thumbnail creation, 3:4 processing, phash.
- `shoe_image_sourcing/dedupe.py`: duplicate grouping logic.
- `shoe_image_sourcing/adapters/base.py`: platform adapter interface.
- `shoe_image_sourcing/adapters/search_pages.py`: generic search-link based MVP adapters for public pages.
- `shoe_image_sourcing/crawler.py`: orchestrates adapters, downloads images, records logs.
- `shoe_image_sourcing/static/index.html`: UI.
- `shoe_image_sourcing/static/app.js`: frontend API calls and gallery behavior.
- `shoe_image_sourcing/static/styles.css`: UI styles.
- `tests/test_query.py`: query generation tests.
- `tests/test_image_processing.py`: 3:4 and validation tests.
- `tests/test_dedupe.py`: duplicate grouping tests.
- `tests/test_storage.py`: manifest and run folder tests.
- `requirements-shoe-sourcing.txt`: deployment dependencies.
- `Procfile`: Render/Railway style web process.
- `README-shoe-image-sourcing.md`: setup, run, and deployment instructions.

---

### Task 1: Project Scaffold and Models

**Files:**
- Create: `shoe_image_sourcing/__init__.py`
- Create: `shoe_image_sourcing/config.py`
- Create: `shoe_image_sourcing/models.py`
- Create: `requirements-shoe-sourcing.txt`
- Create: `tests/test_query.py`

**Interfaces:**
- Produces: `ProductFacts`, `PlatformConfig`, `ImageCandidate`, `RunManifest`, `DEFAULT_PLATFORMS`, `OPTIONAL_PLATFORMS`.

- [ ] **Step 1: Write the failing model/import test**

Create `tests/test_query.py` with:

```python
from shoe_image_sourcing.config import DEFAULT_PLATFORMS, OPTIONAL_PLATFORMS
from shoe_image_sourcing.models import ProductFacts


def test_platform_defaults_include_ozon_reference_sources():
    names = {platform.name for platform in DEFAULT_PLATFORMS}
    assert {"wildberries", "yandex_images", "ozon", "ebay", "stockx", "goat"}.issubset(names)


def test_optional_platforms_are_disabled_by_default():
    assert all(not platform.enabled_by_default for platform in OPTIONAL_PLATFORMS)


def test_product_facts_normalizes_empty_fields():
    facts = ProductFacts(brand=" Nike ", model="", sku=None, color=" white navy ", keywords="")
    assert facts.brand == "Nike"
    assert facts.model is None
    assert facts.sku is None
    assert facts.color == "white navy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_query.py -v`

Expected: FAIL because `shoe_image_sourcing` does not exist.

- [ ] **Step 3: Create package files**

Create `shoe_image_sourcing/__init__.py`:

```python
"""Public shoe image sourcing web app."""
```

Create `shoe_image_sourcing/models.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PlatformConfig(BaseModel):
    name: str
    label: str
    enabled_by_default: bool = True
    competitor_reference_only: bool = False


class ProductFacts(BaseModel):
    brand: str | None = None
    model: str | None = None
    sku: str | None = None
    color: str | None = None
    keywords: str | None = None

    @field_validator("brand", "model", "sku", "color", "keywords", mode="before")
    @classmethod
    def normalize_blank(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None


class ImageCandidate(BaseModel):
    id: str
    platform: str
    source_page_url: str
    image_url: str
    title: str | None = None
    local_original_path: str | None = None
    local_thumbnail_path: str | None = None
    local_processed_path: str | None = None
    width: int | None = None
    height: int | None = None
    duplicate_group_id: str | None = None
    status_labels: list[str] = Field(default_factory=list)


class RunManifest(BaseModel):
    run_id: str
    created_at: datetime
    facts: ProductFacts
    queries: list[str]
    platforms: list[str]
    candidates: list[ImageCandidate] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    status: Literal["created", "running", "complete", "failed"] = "created"
```

Create `shoe_image_sourcing/config.py`:

```python
from pathlib import Path

from .models import PlatformConfig


OUTPUT_ROOT = Path("outputs/shoe_image_sourcing/runs")
MAX_UPLOAD_MB = 8
MAX_IMAGES_PER_RUN = 80
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

DEFAULT_PLATFORMS = [
    PlatformConfig(name="wildberries", label="WB / Wildberries"),
    PlatformConfig(name="yandex_images", label="Yandex Images"),
    PlatformConfig(name="ozon", label="Ozon", competitor_reference_only=True),
    PlatformConfig(name="ebay", label="eBay"),
    PlatformConfig(name="official", label="Brand official site/search"),
    PlatformConfig(name="lamoda", label="Lamoda"),
    PlatformConfig(name="avito", label="Avito"),
    PlatformConfig(name="stockx", label="StockX"),
    PlatformConfig(name="goat", label="GOAT"),
]

OPTIONAL_PLATFORMS = [
    PlatformConfig(name="amazon", label="Amazon", enabled_by_default=False),
    PlatformConfig(name="aliexpress", label="AliExpress", enabled_by_default=False),
    PlatformConfig(name="farfetch", label="Farfetch", enabled_by_default=False),
    PlatformConfig(name="megamarket", label="Мегамаркет", enabled_by_default=False),
    PlatformConfig(name="kazanexpress", label="KazanExpress / Магнит Маркет", enabled_by_default=False),
]
```

Create `requirements-shoe-sourcing.txt`:

```text
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.19
pydantic==2.10.4
httpx==0.28.1
pillow==11.0.0
imagehash==4.3.1
pytest==8.3.4
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_query.py -v`

Expected: PASS.

---

### Task 2: Query Generation

**Files:**
- Create: `shoe_image_sourcing/query.py`
- Modify: `tests/test_query.py`

**Interfaces:**
- Consumes: `ProductFacts`.
- Produces: `generate_queries(facts: ProductFacts) -> list[str]`.

- [ ] **Step 1: Add failing query tests**

Append to `tests/test_query.py`:

```python
from shoe_image_sourcing.query import generate_queries


def test_generate_queries_prioritizes_sku_and_shoe_terms():
    facts = ProductFacts(brand="Nike", model="Air Monarch IV", sku="415445-102", color="White Navy")
    queries = generate_queries(facts)
    assert queries[0] == "Nike Air Monarch IV 415445-102 White Navy shoes"
    assert "Nike Air Monarch IV 415445-102 кроссовки" in queries
    assert "415445-102 Nike shoe product photos" in queries


def test_generate_queries_uses_keywords_when_sku_missing():
    facts = ProductFacts(brand="Nike", keywords="white navy dad shoes")
    queries = generate_queries(facts)
    assert "Nike white navy dad shoes shoes" in queries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_query.py::test_generate_queries_prioritizes_sku_and_shoe_terms -v`

Expected: FAIL because `shoe_image_sourcing.query` does not exist.

- [ ] **Step 3: Implement query generation**

Create `shoe_image_sourcing/query.py`:

```python
from .models import ProductFacts


def _join(parts: list[str | None]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def generate_queries(facts: ProductFacts) -> list[str]:
    base = _join([facts.brand, facts.model, facts.sku, facts.color])
    keyword_base = _join([facts.brand, facts.keywords])
    primary = base or keyword_base or "shoe product"
    sku = facts.sku or primary

    queries = [
        f"{primary} shoes",
        f"{primary} кроссовки",
        f"{sku} {facts.brand or ''} shoe product photos".strip(),
        f"{primary} купить",
        f"{primary} фото обуви",
    ]
    if keyword_base and keyword_base != primary:
        queries.append(f"{keyword_base} shoes")

    unique = []
    seen = set()
    for query in queries:
        normalized = " ".join(query.split())
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_query.py -v`

Expected: PASS.

---

### Task 3: Storage and Manifest

**Files:**
- Create: `shoe_image_sourcing/storage.py`
- Create: `tests/test_storage.py`

**Interfaces:**
- Produces: `create_run(facts, queries, platforms, output_root) -> RunManifest`, `save_manifest(manifest, run_dir)`, `load_manifest(run_dir)`.

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_storage.py`:

```python
from pathlib import Path

from shoe_image_sourcing.models import ProductFacts
from shoe_image_sourcing.storage import create_run, load_manifest, save_manifest


def test_create_run_builds_expected_directories(tmp_path):
    manifest, run_dir = create_run(
        facts=ProductFacts(brand="Nike"),
        queries=["Nike shoes"],
        platforms=["ebay"],
        output_root=tmp_path,
    )
    assert run_dir.exists()
    for name in ["input", "originals", "processed_3x4", "thumbnails"]:
        assert (run_dir / name).is_dir()
    assert manifest.status == "created"


def test_manifest_round_trip(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike"), ["Nike shoes"], ["ebay"], tmp_path)
    manifest.logs.append("started")
    save_manifest(manifest, run_dir)
    loaded = load_manifest(run_dir)
    assert loaded.run_id == manifest.run_id
    assert loaded.logs == ["started"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`

Expected: FAIL because `shoe_image_sourcing.storage` does not exist.

- [ ] **Step 3: Implement storage**

Create `shoe_image_sourcing/storage.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .models import ProductFacts, RunManifest


def create_run(
    facts: ProductFacts,
    queries: list[str],
    platforms: list[str],
    output_root: Path,
) -> tuple[RunManifest, Path]:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    run_dir = output_root / run_id
    for name in ["input", "originals", "processed_3x4", "thumbnails"]:
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(
        run_id=run_id,
        created_at=datetime.now(),
        facts=facts,
        queries=queries,
        platforms=platforms,
    )
    save_manifest(manifest, run_dir)
    return manifest, run_dir


def save_manifest(manifest: RunManifest, run_dir: Path) -> None:
    (run_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )


def load_manifest(run_dir: Path) -> RunManifest:
    return RunManifest.model_validate_json((run_dir / "manifest.json").read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_storage.py -v`

Expected: PASS.

---

### Task 4: Image Processing and Dedupe

**Files:**
- Create: `shoe_image_sourcing/image_processing.py`
- Create: `shoe_image_sourcing/dedupe.py`
- Create: `tests/test_image_processing.py`
- Create: `tests/test_dedupe.py`

**Interfaces:**
- Produces: `process_to_3x4(src, dest) -> tuple[int, int]`, `make_thumbnail(src, dest) -> tuple[int, int]`, `compute_phash(path) -> str`, `group_duplicates(candidates, max_distance=6)`.

- [ ] **Step 1: Write failing image tests**

Create `tests/test_image_processing.py`:

```python
from PIL import Image

from shoe_image_sourcing.image_processing import compute_phash, make_thumbnail, process_to_3x4


def test_process_to_3x4_outputs_expected_ratio(tmp_path):
    src = tmp_path / "src.jpg"
    dest = tmp_path / "out.jpg"
    Image.new("RGB", (1000, 500), "white").save(src)
    width, height = process_to_3x4(src, dest)
    assert dest.exists()
    assert (width, height) == (900, 1200)


def test_thumbnail_and_hash(tmp_path):
    src = tmp_path / "src.jpg"
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (800, 800), "white").save(src)
    make_thumbnail(src, thumb)
    assert thumb.exists()
    assert len(compute_phash(src)) >= 16
```

Create `tests/test_dedupe.py`:

```python
from shoe_image_sourcing.dedupe import hamming_distance


def test_hamming_distance_hex_hashes():
    assert hamming_distance("ffff", "ffff") == 0
    assert hamming_distance("ffff", "0000") == 16
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_image_processing.py tests/test_dedupe.py -v`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement image processing**

Create `shoe_image_sourcing/image_processing.py`:

```python
from pathlib import Path

import imagehash
from PIL import Image, ImageOps


TARGET_SIZE = (900, 1200)


def _open_rgb(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def process_to_3x4(src: Path, dest: Path) -> tuple[int, int]:
    image = _open_rgb(src)
    image.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", TARGET_SIZE, "white")
    x = (TARGET_SIZE[0] - image.width) // 2
    y = (TARGET_SIZE[1] - image.height) // 2
    canvas.paste(image, (x, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, quality=92)
    return canvas.size


def make_thumbnail(src: Path, dest: Path, max_size: tuple[int, int] = (320, 420)) -> tuple[int, int]:
    image = ImageOps.exif_transpose(_open_rgb(src))
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, quality=85)
    return image.size


def compute_phash(path: Path) -> str:
    return str(imagehash.phash(_open_rgb(path)))
```

Create `shoe_image_sourcing/dedupe.py`:

```python
from __future__ import annotations

from .models import ImageCandidate


def hamming_distance(hex_a: str, hex_b: str) -> int:
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def group_duplicates(candidates: list[ImageCandidate], hashes: dict[str, str], max_distance: int = 6) -> list[ImageCandidate]:
    groups: list[tuple[str, str]] = []
    for candidate in candidates:
        image_hash = hashes.get(candidate.id)
        if not image_hash:
            continue
        assigned = None
        for group_id, group_hash in groups:
            if hamming_distance(image_hash, group_hash) <= max_distance:
                assigned = group_id
                break
        if assigned is None:
            assigned = f"dup-{len(groups) + 1}"
            groups.append((assigned, image_hash))
        candidate.duplicate_group_id = assigned
    return candidates
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_image_processing.py tests/test_dedupe.py -v`

Expected: PASS.

---

### Task 5: Platform Adapters and Crawler

**Files:**
- Create: `shoe_image_sourcing/adapters/__init__.py`
- Create: `shoe_image_sourcing/adapters/base.py`
- Create: `shoe_image_sourcing/adapters/search_pages.py`
- Create: `shoe_image_sourcing/crawler.py`
- Create: `tests/test_dedupe.py` additions

**Interfaces:**
- Produces: `PlatformAdapter.search(query, limit) -> list[ImageCandidate]`, `collect_candidates(manifest, run_dir, limit_per_platform=12) -> RunManifest`.

- [ ] **Step 1: Add adapter URL construction tests**

Append to `tests/test_dedupe.py`:

```python
from shoe_image_sourcing.adapters.search_pages import build_search_url


def test_build_search_url_for_known_platforms():
    assert "wildberries.ru" in build_search_url("wildberries", "Nike shoes")
    assert "yandex" in build_search_url("yandex_images", "Nike shoes")
    assert "ozon.ru" in build_search_url("ozon", "Nike shoes")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dedupe.py::test_build_search_url_for_known_platforms -v`

Expected: FAIL because adapter module does not exist.

- [ ] **Step 3: Implement adapters**

Create `shoe_image_sourcing/adapters/__init__.py`:

```python
"""Crawler adapters."""
```

Create `shoe_image_sourcing/adapters/base.py`:

```python
from abc import ABC, abstractmethod

from shoe_image_sourcing.models import ImageCandidate


class PlatformAdapter(ABC):
    platform: str

    @abstractmethod
    async def search(self, query: str, limit: int = 12) -> list[ImageCandidate]:
        raise NotImplementedError
```

Create `shoe_image_sourcing/adapters/search_pages.py`:

```python
from __future__ import annotations

from hashlib import sha1
from urllib.parse import quote_plus

from .base import PlatformAdapter
from shoe_image_sourcing.models import ImageCandidate


SEARCH_PATTERNS = {
    "wildberries": "https://www.wildberries.ru/catalog/0/search.aspx?search={query}",
    "yandex_images": "https://yandex.com/images/search?text={query}",
    "ozon": "https://www.ozon.ru/search/?text={query}",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw={query}",
    "official": "https://www.google.com/search?tbm=isch&q={query}+official+product+images",
    "lamoda": "https://www.lamoda.ru/catalogsearch/result/?q={query}",
    "avito": "https://www.avito.ru/all?q={query}",
    "stockx": "https://stockx.com/search?s={query}",
    "goat": "https://www.goat.com/search?query={query}",
    "amazon": "https://www.amazon.com/s?k={query}",
    "aliexpress": "https://www.aliexpress.com/wholesale?SearchText={query}",
    "farfetch": "https://www.farfetch.com/search?q={query}",
    "megamarket": "https://megamarket.ru/catalog/?q={query}",
    "kazanexpress": "https://kazanexpress.ru/search?query={query}",
}


def build_search_url(platform: str, query: str) -> str:
    pattern = SEARCH_PATTERNS[platform]
    return pattern.format(query=quote_plus(query))


class SearchPageAdapter(PlatformAdapter):
    def __init__(self, platform: str):
        self.platform = platform

    async def search(self, query: str, limit: int = 12) -> list[ImageCandidate]:
        search_url = build_search_url(self.platform, query)
        candidate_id = sha1(f"{self.platform}:{query}".encode("utf-8")).hexdigest()[:16]
        return [
            ImageCandidate(
                id=candidate_id,
                platform=self.platform,
                source_page_url=search_url,
                image_url="",
                title=f"Search results for {query}",
                status_labels=["search_page_only"],
            )
        ]
```

- [ ] **Step 4: Implement crawler skeleton**

Create `shoe_image_sourcing/crawler.py`:

```python
from __future__ import annotations

from pathlib import Path

from .adapters.search_pages import SearchPageAdapter
from .models import RunManifest
from .storage import save_manifest


async def collect_candidates(manifest: RunManifest, run_dir: Path, limit_per_platform: int = 12) -> RunManifest:
    manifest.status = "running"
    manifest.logs.append("crawl started")
    for platform in manifest.platforms:
        adapter = SearchPageAdapter(platform)
        for query in manifest.queries[:2]:
            try:
                candidates = await adapter.search(query, limit=limit_per_platform)
                for candidate in candidates:
                    if platform == "ozon" and "competitor_reference_only" not in candidate.status_labels:
                        candidate.status_labels.append("competitor_reference_only")
                manifest.candidates.extend(candidates)
                manifest.logs.append(f"{platform}: collected {len(candidates)} search entries for {query}")
            except Exception as exc:
                manifest.logs.append(f"{platform}: failed for {query}: {exc}")
    manifest.status = "complete"
    save_manifest(manifest, run_dir)
    return manifest
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_dedupe.py -v`

Expected: PASS.

---

### Task 6: FastAPI Backend

**Files:**
- Create: `shoe_image_sourcing/app.py`
- Create: `tests/test_storage.py` additions

**Interfaces:**
- Produces HTTP routes: `GET /api/platforms`, `POST /api/runs`, `GET /api/runs/{run_id}`.

- [ ] **Step 1: Add API smoke test**

Append to `tests/test_storage.py`:

```python
from fastapi.testclient import TestClient

from shoe_image_sourcing.app import app


def test_platforms_endpoint_returns_defaults():
    client = TestClient(app)
    response = client.get("/api/platforms")
    assert response.status_code == 200
    data = response.json()
    assert any(platform["name"] == "ozon" for platform in data["default"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py::test_platforms_endpoint_returns_defaults -v`

Expected: FAIL because `shoe_image_sourcing.app` does not exist.

- [ ] **Step 3: Implement FastAPI app**

Create `shoe_image_sourcing/app.py`:

```python
from __future__ import annotations

import shutil
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

    input_path = run_dir / "input" / image.filename
    with input_path.open("wb") as handle:
        shutil.copyfileobj(image.file, handle, length=1024 * 1024 * MAX_UPLOAD_MB)

    background_tasks.add_task(collect_candidates, manifest, run_dir)
    return {"run_id": manifest.run_id, "status": manifest.status, "queries": queries}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run_dir = OUTPUT_ROOT / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return load_manifest(run_dir).model_dump()
```

- [ ] **Step 4: Run API test**

Run: `pytest tests/test_storage.py::test_platforms_endpoint_returns_defaults -v`

Expected: PASS.

---

### Task 7: Frontend UI

**Files:**
- Create: `shoe_image_sourcing/static/index.html`
- Create: `shoe_image_sourcing/static/app.js`
- Create: `shoe_image_sourcing/static/styles.css`

**Interfaces:**
- Consumes: `/api/platforms`, `/api/runs`, `/api/runs/{run_id}`.
- Produces: Browser UI for upload, platform selection, progress logs, candidate gallery.

- [ ] **Step 1: Create frontend files**

Create `shoe_image_sourcing/static/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>鞋类图源采集台</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <main class="shell">
    <aside class="panel">
      <h1>鞋类图源采集台</h1>
      <form id="run-form">
        <label>产品主图 <input name="image" type="file" accept="image/*" required /></label>
        <label>品牌 <input name="brand" placeholder="Nike" /></label>
        <label>型号 <input name="model" placeholder="Air Monarch IV" /></label>
        <label>货号 <input name="sku" placeholder="415445-102" /></label>
        <label>颜色 <input name="color" placeholder="White Navy" /></label>
        <label>补充关键词 <input name="keywords" placeholder="dad shoes" /></label>
        <section>
          <h2>平台</h2>
          <div id="platforms" class="platforms"></div>
        </section>
        <button type="submit">开始采集</button>
      </form>
    </aside>
    <section class="workspace">
      <div class="status">
        <strong id="run-title">等待开始</strong>
        <pre id="logs"></pre>
      </div>
      <div id="gallery" class="gallery"></div>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

Create `shoe_image_sourcing/static/styles.css`:

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, sans-serif; background: #f6f7f8; color: #202124; }
.shell { display: grid; grid-template-columns: 320px 1fr; min-height: 100vh; }
.panel { background: #fff; border-right: 1px solid #ddd; padding: 20px; overflow: auto; }
h1 { font-size: 22px; margin: 0 0 18px; }
h2 { font-size: 15px; margin: 18px 0 10px; }
label { display: grid; gap: 6px; margin-bottom: 12px; font-size: 14px; }
input { border: 1px solid #ccc; border-radius: 6px; padding: 9px; font-size: 14px; }
button { width: 100%; border: 0; border-radius: 6px; padding: 11px; background: #111; color: #fff; font-weight: 700; cursor: pointer; }
.platforms { display: grid; gap: 8px; margin-bottom: 16px; }
.platforms label { display: flex; align-items: center; gap: 8px; margin: 0; }
.workspace { padding: 20px; }
.status { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 14px; margin-bottom: 18px; }
pre { white-space: pre-wrap; max-height: 180px; overflow: auto; color: #555; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; }
.card { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 10px; min-height: 150px; }
.card img { width: 100%; aspect-ratio: 3 / 4; object-fit: contain; background: #fafafa; border-radius: 6px; }
.meta { font-size: 12px; color: #555; margin-top: 8px; word-break: break-all; }
.tag { display: inline-block; margin-top: 6px; padding: 3px 6px; border-radius: 999px; background: #eef2ff; color: #263a8b; font-size: 12px; }
```

Create `shoe_image_sourcing/static/app.js`:

```javascript
const form = document.querySelector("#run-form");
const platformBox = document.querySelector("#platforms");
const logs = document.querySelector("#logs");
const gallery = document.querySelector("#gallery");
const runTitle = document.querySelector("#run-title");

async function loadPlatforms() {
  const res = await fetch("/api/platforms");
  const data = await res.json();
  [...data.default, ...data.optional].forEach((platform) => {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" value="${platform.name}" ${platform.enabled_by_default ? "checked" : ""}> ${platform.label}`;
    platformBox.appendChild(label);
  });
}

function selectedPlatforms() {
  return [...platformBox.querySelectorAll("input:checked")].map((input) => input.value).join(",");
}

async function pollRun(runId) {
  const res = await fetch(`/api/runs/${runId}`);
  const run = await res.json();
  runTitle.textContent = `任务 ${run.run_id} · ${run.status}`;
  logs.textContent = run.logs.join("\n");
  gallery.innerHTML = "";
  run.candidates.forEach((candidate) => {
    const card = document.createElement("article");
    card.className = "card";
    const tags = candidate.status_labels.map((tag) => `<span class="tag">${tag}</span>`).join(" ");
    card.innerHTML = `
      <div class="meta"><strong>${candidate.platform}</strong></div>
      <div class="meta"><a href="${candidate.source_page_url}" target="_blank">来源链接</a></div>
      <div class="meta">${candidate.title || ""}</div>
      ${tags}
    `;
    gallery.appendChild(card);
  });
  if (run.status === "running" || run.status === "created") {
    setTimeout(() => pollRun(runId), 1500);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = new FormData(form);
  body.set("platforms", selectedPlatforms());
  runTitle.textContent = "正在创建任务...";
  const res = await fetch("/api/runs", { method: "POST", body });
  const data = await res.json();
  pollRun(data.run_id);
});

loadPlatforms();
```

- [ ] **Step 2: Manually verify UI**

Run: `uvicorn shoe_image_sourcing.app:app --reload --port 8765`

Open: `http://127.0.0.1:8765`

Expected: Upload form, platform checkboxes, and gallery area render.

---

### Task 8: Deployment Docs and Process Files

**Files:**
- Create: `Procfile`
- Create: `README-shoe-image-sourcing.md`

**Interfaces:**
- Produces: documented GitHub deployment path.

- [ ] **Step 1: Add process file**

Create `Procfile`:

```text
web: uvicorn shoe_image_sourcing.app:app --host 0.0.0.0 --port $PORT
```

- [ ] **Step 2: Add README**

Create `README-shoe-image-sourcing.md`:

```markdown
# Shoe Image Sourcing Tool

Public web app for sourcing shoe product images from ecommerce and image-search platforms for Ozon-oriented listing preparation.

## Features

- Upload a shoe product image.
- Enter brand, model, SKU, color, and keywords.
- Generate English and Russian search queries.
- Search platform entry points for WB, Yandex Images, Ozon, eBay, official search, Lamoda, Avito, StockX, and GOAT.
- Mark Ozon as competitor reference.
- Prepare for duplicate grouping and 3:4 image processing.

## Local Run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-shoe-sourcing.txt
uvicorn shoe_image_sourcing.app:app --reload --port 8765
```

Open `http://127.0.0.1:8765`.

## Deploy

GitHub Pages alone is not enough because this app needs a Python backend.

Recommended hosts:

- Render
- Railway
- Fly.io

Use:

```text
Build command: pip install -r requirements-shoe-sourcing.txt
Start command: uvicorn shoe_image_sourcing.app:app --host 0.0.0.0 --port $PORT
```

## Limits

- No login-required scraping.
- No得物 App automation.
- No iPhone automation.
- Ozon images are competitor references by default.
- Users are responsible for final image usage rights.
```

- [ ] **Step 3: Full verification**

Run: `pytest tests -v`

Expected: PASS.

Run: `uvicorn shoe_image_sourcing.app:app --port 8765`

Expected: Server starts and `GET /api/platforms` returns platform JSON.

---

## Self-Review

- Spec coverage: The plan covers public deployment, platform scope, query generation, storage, Ozon reference marking, UI, and deployment docs.
- Known MVP limitation: Task 5 creates search-page candidate entries first; full image extraction/download can be added after the shell is working. This is intentional to get a deployable public app before adding brittle platform-specific scraping.
- Placeholder scan: No TBD/TODO placeholders.
- Type consistency: `ProductFacts`, `ImageCandidate`, `RunManifest`, `generate_queries`, `create_run`, `collect_candidates`, and API route names are consistent across tasks.

