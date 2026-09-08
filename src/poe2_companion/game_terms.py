"""Bounded bilingual names for model-facing results; game IDs stay canonical."""
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .builds import DTO, BuildError, bounded_dto
from . import localization


class TermRequest(DTO):
    query: Annotated[str, Field(min_length=1, max_length=160)]
    category: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_]{1,40}$")] | None = None
    limit: Annotated[int, Field(ge=1, le=10)] = 10

    @field_validator("query")
    @classmethod
    def valid_query(cls, value):
        localization.checked_query(value)
        return value


class GameTerm(DTO):
    key: Annotated[str, Field(max_length=160)]
    en: Annotated[str, Field(max_length=160)]
    ko: Annotated[str, Field(max_length=160)]
    categories: Annotated[list[str], Field(max_length=20)]
    source_en: Annotated[str, Field(max_length=1024)]
    source_ko: Annotated[str, Field(max_length=1024)]


class TermResult(DTO):
    entries: Annotated[list[GameTerm], Field(max_length=10)]
    has_more: bool
    catalog_record_count: int
    snapshot_date: str
    game_version: str
    catalog_complete: Literal[False] = False
    policy: Literal["verified_names_only"] = "verified_names_only"


def search_terms(request: TermRequest) -> TermResult:
    records = localization.search(request.query, request.limit + 1, category=request.category)
    meta = localization.metadata()
    entries = [GameTerm(**r.to_dict()) for r in records[:request.limit]]
    while True:
        result = TermResult(entries=entries, has_more=len(records) > len(entries),
            catalog_record_count=meta["record_count"], snapshot_date=meta["snapshot_date"],
            game_version=meta["game_version"])
        try:
            return bounded_dto(result)
        except BuildError:
            if not entries:
                raise
            entries.pop()


def name_fields(name: str, prefix: str = "name") -> dict:
    # Unknown upstream names must remain usable in English. Never translate
    # arbitrary text or select one member of an ambiguous name match.
    try:
        record = localization.lookup(name)
    except ValueError:
        record = None
    return {prefix + "_ko": record.ko if record else None,
            prefix + "_source_ko": record.to_dict()["source_ko"] if record else None}


def english_query(query: str) -> str:
    try:
        return localization.english_query(query)
    except ValueError:
        return query


def localize_engine_result(value):
    calculation = getattr(value, "calculation", value)
    skills = []
    for snapshot in (calculation.baseline, calculation.result):
        if snapshot is not None and snapshot.selected_skill is not None and not snapshot.selected_skill_labels_truncated:
            skill = snapshot.selected_skill
            labels = name_fields(getattr(skill, "gem_name", None) or skill.name or skill.skill_id)
            skill.name_ko = labels["name_ko"]
            skill.name_source_ko = labels["name_source_ko"]
            skills.append((snapshot,skill))
    try:
        return bounded_dto(value)
    except BuildError:
        # Numeric results and issue counts take precedence over optional labels.
        for snapshot,skill in skills:
            skill.name_source_ko = None
            snapshot.selected_skill_labels_truncated = True
        try:
            return bounded_dto(value)
        except BuildError:
            for snapshot,skill in skills:
                skill.name_ko = None
            return bounded_dto(value)
