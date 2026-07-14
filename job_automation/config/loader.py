"""Configuration loading."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from job_automation.paths import RULES_PATH


class SalaryConfig(BaseModel):
    min_annual: int = 80000
    min_hourly: float = 50.0


class KeywordsConfig(BaseModel):
    travel_required: list[str] = Field(default_factory=list)
    travel_not_required: list[str] = Field(default_factory=list)
    clearance: list[str] = Field(default_factory=list)
    security_related: list[str] = Field(default_factory=list)
    government_industry: list[str] = Field(default_factory=list)
    onsite: list[str] = Field(default_factory=list)
    hybrid: list[str] = Field(default_factory=list)
    fully_remote: list[str] = Field(default_factory=list)


class SearchConfig(BaseModel):
    search_queries: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    target_skills: list[str] = Field(default_factory=list)
    excluded_roles: list[str] = Field(default_factory=list)
    experience_levels: list[str] = Field(default_factory=list)
    commitment_types: list[str] = Field(default_factory=list)
    location: str = "United States"
    salary: SalaryConfig = Field(default_factory=SalaryConfig)
    keywords: KeywordsConfig = Field(default_factory=KeywordsConfig)
    portals: list[str] = Field(
        default_factory=lambda: ["hiringcafe", "builtin", "jobright", "glassdoor"]
    )
    max_pages_per_query: int = 3
    portal_concurrency: int = 2
    headless: bool = True


def load_rules(path: Path | None = None) -> SearchConfig:
    rules_path = path or RULES_PATH
    with rules_path.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return SearchConfig.model_validate(data)


@lru_cache
def get_rules() -> SearchConfig:
    return load_rules()
