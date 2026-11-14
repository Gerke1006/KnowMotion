"""History components are validated data, never executable scene instructions."""
from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Short = Annotated[str, Field(min_length=1, max_length=56)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Year = Annotated[float, Field(ge=-10000, le=10000, allow_inf_nan=False)]


class HistoryData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_ids: list[Identifier] = Field(default_factory=list, max_length=12)


class Location(HistoryData):
    id: Identifier
    name: Short
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    lat: float = Field(ge=-85, le=85, allow_inf_nan=False)
    year: Year | None = None
    description: str = Field(default="", max_length=120)


class Route(HistoryData):
    id: Identifier | None = None
    from_: Identifier = Field(alias="from")
    to: Identifier
    label: str = Field(default="", max_length=56)
    kind: Literal["schematic"] = "schematic"


class Viewport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)
    south: float = Field(ge=-85, le=85, allow_inf_nan=False)
    north: float = Field(ge=-85, le=85, allow_inf_nan=False)

    @model_validator(mode="after")
    def increasing(self):
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("Map viewport bounds must increase; dateline crossing is not supported")
        return self


class HistoryMap(HistoryData):
    title: str = Field(default="", max_length=56)
    locations: list[Location] = Field(min_length=2, max_length=8)
    routes: list[Route] = Field(default_factory=list, max_length=12)
    viewport: Viewport | None = None
    note: str = Field(default="地点为近似定位；连线为交流示意，不表示古代国界或精确行程。", max_length=140)

    @model_validator(mode="after")
    def connected(self):
        ids = [point.id for point in self.locations]
        if len(ids) != len(set(ids)):
            raise ValueError("History map location ids must be unique")
        route_ids = [route.id for route in self.routes if route.id]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("History map route ids must be unique")
        for route in self.routes:
            if route.from_ not in ids or route.to not in ids or route.from_ == route.to:
                raise ValueError("History map route endpoints must name two different existing locations")
        if self.viewport:
            view = self.viewport
            if any(not view.west <= point.lon <= view.east or not view.south <= point.lat <= view.north
                   for point in self.locations):
                raise ValueError("History map viewport must include every location")
        return self


class Event(HistoryData):
    year: Year
    date_label: str | None = Field(default=None, min_length=1, max_length=40)
    label: Short
    detail: str = Field(default="", max_length=120)

    @field_validator("year")
    @classmethod
    def no_year_zero(cls, year):
        if year == 0:
            raise ValueError("Use historical BCE/CE years: there is no year zero")
        return year


class HistoryTimeline(HistoryData):
    title: str = Field(default="", max_length=56)
    events: list[Event] = Field(min_length=2, max_length=7)
    range: tuple[Year, Year] | None = None
    note: str = Field(default="时间先后不自动构成因果关系。", max_length=140)

    @model_validator(mode="after")
    def chronological(self):
        self.events.sort(key=lambda event: event.year)
        if self.range and (self.range[0] >= self.range[1]
                           or self.events[0].year < self.range[0]
                           or self.events[-1].year > self.range[1]):
            raise ValueError("Timeline range must increase and contain all event years")
        return self


class RelatedPerson(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: Short
    relation: str = Field(min_length=1, max_length=80)


class HistoryPerson(HistoryData):
    name: Short
    role: str = Field(min_length=1, max_length=80)
    years: str = Field(default="", max_length=56)
    facts: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(min_length=1, max_length=4)
    portrait_asset: str | None = None
    related: list[RelatedPerson] = Field(default_factory=list, max_length=4)

    @field_validator("portrait_asset")
    @classmethod
    def safe_asset(cls, value):
        if value is None:
            return value
        path = PurePosixPath(value)
        if ("\\" in value or ":" in value or path.is_absolute() or ".." in path.parts
                or not path.parts or path.parts[0] != "portraits"
                or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}):
            raise ValueError("portrait_asset must be an approved relative portraits/ image path, never a URL or traversal")
        return value


CONTRACTS = {"history.map": HistoryMap, "history.timeline": HistoryTimeline, "history.person": HistoryPerson}


def referenced_source_ids(value) -> set[str]:
    """Collect component and per-record citations for the renderer's source legend."""
    if isinstance(value, dict):
        result = set(value.get("source_ids", []))
        for nested in value.values():
            result.update(referenced_source_ids(nested))
        return result
    if isinstance(value, list):
        result = set()
        for nested in value:
            result.update(referenced_source_ids(nested))
        return result
    return set()


def validate_history_parameters(kind: str, parameters: dict, *, sources: list[dict] | None = None,
                                require_sources: bool = False) -> dict:
    if kind not in CONTRACTS:
        raise ValueError(f"Unsupported history component: {kind}")
    result = CONTRACTS[kind].model_validate(copy.deepcopy(parameters)).model_dump(mode="json", by_alias=True, exclude_none=True)
    allowed = {source["id"] for source in sources or [] if isinstance(source.get("id"), str)}
    if require_sources and not result["source_ids"]:
        raise ValueError(f"{kind} requires source_ids from the retrieved evidence")

    def check(value):
        if isinstance(value, dict):
            if sources is not None and set(value.get("source_ids", [])) - allowed:
                raise ValueError(f"{kind} cites source_ids that are not in the retrieved evidence")
            for nested in value.values():
                check(nested)
        elif isinstance(value, list):
            for nested in value:
                check(nested)

    check(result)
    return result


def normalize_history_component(component: dict, *, sources: list[dict] | None = None,
                                require_sources: bool = False) -> dict:
    result = copy.deepcopy(component)
    result["parameters"] = validate_history_parameters(result["id"], result.get("parameters", {}),
                                                       sources=sources, require_sources=require_sources)
    return result
