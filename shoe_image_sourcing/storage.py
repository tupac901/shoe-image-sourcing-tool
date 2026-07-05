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
    manifest_path = run_dir / "manifest.json"
    temp_path = run_dir / "manifest.json.tmp"
    temp_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    temp_path.replace(manifest_path)


def load_manifest(run_dir: Path) -> RunManifest:
    return RunManifest.model_validate_json((run_dir / "manifest.json").read_text(encoding="utf-8"))
