"""Pinned typed game entities and complete native passive graph contracts."""
from typing import Annotated, Literal
from pydantic import Field
from .builds import DTO

NodeID = Annotated[int, Field(ge=0, le=2147483647)]
BuildRef = Annotated[str, Field(pattern=r'^bld_[0-9a-f]{32}$')]


class PassiveNode(DTO):
    node_id: NodeID
    name: Annotated[str, Field(max_length=240)]
    name_ko: Annotated[str, Field(max_length=240)] | None = None
    translation_source: Annotated[str, Field(max_length=1024)] | None = None
    type: Annotated[str, Field(max_length=40)]
    stats: Annotated[list[Annotated[str, Field(max_length=2000)]], Field(max_length=32)]
    linked_node_ids: Annotated[list[NodeID], Field(max_length=64)]
    x: float
    y: float
    group_id: int
    ascendancy: Annotated[str, Field(max_length=80)] | None = None
    allocated: bool
    allocation_mode: Literal[0,1,2]
    attribute_choice_required: bool
    special_allocation_rule: bool
    recipe: Annotated[list[Annotated[str, Field(max_length=120)]], Field(max_length=8)]
    recipe_catalog_id: Annotated[str, Field(max_length=80)] | None = None


class GemLevel(DTO):
    native_level: int
    character_level_required: int
    strength_required: float
    dexterity_required: float
    intelligence_required: float


class GemDefinition(DTO):
    catalog_id: Annotated[str, Field(max_length=160)]
    skill_id: Annotated[str, Field(max_length=120)]
    name: Annotated[str, Field(max_length=240)]
    support: bool
    natural_max_level: int
    levels: Annotated[list[GemLevel], Field(max_length=100)]
    level_count: int | None = None
    next_level_offset: int | None = None
    # Native gem requirements are separate from effective skill levels.
    requirements_scope: Literal['native_gem_before_build_modifiers'] = 'native_gem_before_build_modifiers'


class RuneDefinition(DTO):
    catalog_id: Annotated[str, Field(max_length=160)]
    name: Annotated[str, Field(max_length=160)]
    slot_types: Annotated[list[Annotated[str, Field(max_length=80)]], Field(max_length=32)]


class NativeCatalog(DTO):
    tree_version: Annotated[str, Field(max_length=24)]
    nodes: Annotated[list[PassiveNode], Field(max_length=30000)]
    gems: Annotated[list[GemDefinition], Field(max_length=10000)]
    runes: Annotated[list[RuneDefinition], Field(max_length=3000)]
    class_start_node_id: NodeID
    ascendancy_start_node_id: NodeID | None = None


class CatalogRequest(DTO):
    build_id: BuildRef
    entity_type: Literal['passive','gem','rune']
    query: Annotated[str, Field(max_length=100, pattern=r'^[^\x00-\x1f\x7f]*$')] = ''
    node_ids: Annotated[list[NodeID], Field(max_length=20)] = Field(default_factory=list)
    catalog_id: Annotated[str, Field(max_length=160)] | None = None
    level_offset: Annotated[int, Field(ge=0, le=100)] = 0
    level_limit: Annotated[int, Field(ge=1, le=8)] = 3
    offset: Annotated[int, Field(ge=0, le=30000)] = 0
    limit: Annotated[int, Field(ge=1, le=10)] = 5


class CatalogPage(DTO):
    build_id: BuildRef
    entity_type: Literal['passive','gem','rune']
    tree_version: str
    data_revision: str
    passives: Annotated[list[PassiveNode], Field(max_length=10)] = Field(default_factory=list)
    gems: Annotated[list[GemDefinition], Field(max_length=10)] = Field(default_factory=list)
    runes: Annotated[list[RuneDefinition], Field(max_length=10)] = Field(default_factory=list)
    total: int
    next_offset: int | None
    catalog_scope: Literal['pinned_native_data'] = 'pinned_native_data'
    effect_implementation_proven: Literal[False] = False


class PassiveRouteRequest(DTO):
    build_id: BuildRef
    tree_revision: Annotated[str, Field(max_length=24)]
    target_node_ids: Annotated[list[NodeID], Field(min_length=1, max_length=8)]
    refund_node_ids: Annotated[list[NodeID], Field(max_length=64)] = Field(default_factory=list)
    ordinary_points_available: Annotated[int, Field(ge=0, le=64)]
    ascendancy_points_available: Annotated[int, Field(ge=0, le=8)] = 0
    allocation_mode: Literal[0,1,2] = 0
    offset: Annotated[int, Field(ge=0, le=10000)] = 0
    limit: Annotated[int, Field(ge=1, le=10)] = 8


class RouteStep(DTO):
    node_id: NodeID
    name: str
    name_ko: str | None = None
    translation_source: str | None = None
    connected_from_node_id: NodeID
    landmark: Annotated[str, Field(max_length=240)]
    point_pool: Literal['ordinary','ascendancy']
    attribute_choice_required: bool


class PassiveRoute(DTO):
    build_id: BuildRef
    tree_revision: str
    data_revision: str
    status: Literal['route_found','over_budget','disconnected_after_refund','no_route','unsupported_node_rule']
    steps: Annotated[list[RouteStep], Field(max_length=10)]
    total_steps: int
    next_offset: int | None = None
    disconnected_node_ids: Annotated[list[NodeID], Field(max_length=32)] = Field(default_factory=list)
    refund_node_ids: list[NodeID]
    ordinary_points_cost: int
    ascendancy_points_cost: int
    requested_targets: list[NodeID]
    algorithm: Literal['deterministic_shortest_path_per_target'] = 'deterministic_shortest_path_per_target'
    global_optimum_proven: Literal[False] = False
    metric_gain_requires_experiment: Literal[True] = True
