from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PlatformConfig(BaseModel):
    name: str
    label: str
    enabled_by_default: bool = True
    competitor_reference_only: bool = False
    speed_tier: Literal["fast", "deep"] = "fast"


class ProductFacts(BaseModel):
    product_text: str | None = None
    brand: str | None = None
    model: str | None = None
    sku: str | None = None
    color: str | None = None
    keywords: str | None = None

    @field_validator("product_text", "brand", "model", "sku", "color", "keywords", mode="before")
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
