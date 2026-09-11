"""Closed immutable changesets; all game entities must be discovered first."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO, PlayerStat
from .profiles import BuildRef, Digest, SkillInstanceID
from .subjects import CalculationTarget, SubjectBinding
from .calculation_config import CalculationConfiguration
from .combat_models import CombatScenario
from .engine_models import EngineSlot, EngineCalculation

NodeID = Annotated[int, Field(ge=0, le=2147483647)]
CatalogID = Annotated[str, Field(pattern=r'^[A-Za-z0-9_ /:\x27.-]+$', min_length=1, max_length=160)]
ExperimentID = Annotated[str, Field(pattern=r'^exp_[0-9a-f]{32}$')]


class SetGem(DTO):
    type: Literal['set_gem']
    skill_instance_id: SkillInstanceID
    native_level: Annotated[int, Field(ge=1, le=100)]
    quality: Annotated[int, Field(ge=0, le=100)]


class SetSupports(DTO):
    type: Literal['set_supports']
    skill_instance_id: SkillInstanceID
    support_gem_ids: Annotated[list[CatalogID], Field(max_length=10)]
    # Capacity belongs to this skill gem, not to a previously owned gem.
    observed_socket_capacity: Annotated[int, Field(ge=0, le=10)]
    socket_capacity_evidence: Literal['user_reported', 'planned_upgrade'] = 'user_reported'
    original_observed_socket_capacity: Annotated[int, Field(ge=0, le=10)] | None = None


class AttributeChoice(DTO):
    node_id: NodeID
    attribute: Literal['strength', 'dexterity', 'intelligence']


class AllocatePassives(DTO):
    type: Literal['allocate_passives']
    node_ids: Annotated[list[NodeID], Field(min_length=1, max_length=64)]
    attribute_choices: Annotated[list[AttributeChoice], Field(max_length=64)] = Field(default_factory=list)
    allocation_mode: Literal[0, 1, 2] = 0


class RefundPassives(DTO):
    type: Literal['refund_passives']
    node_ids: Annotated[list[NodeID], Field(min_length=1, max_length=64)]


class SetAscendancy(DTO):
    type: Literal['set_ascendancy']
    allocate_node_ids: Annotated[list[NodeID], Field(max_length=16)]
    refund_node_ids: Annotated[list[NodeID], Field(max_length=16)]


class SavedItemSource(DTO):
    kind: Literal['saved_item']
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)]


class RetainedItemSource(DTO):
    kind: Literal['retained_trade_listing']
    search_id: Annotated[str, Field(pattern=r'^ts_[0-9a-f]{32}$')]
    listing_ref: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class EquipItem(DTO):
    type: Literal['equip_item']
    slot: EngineSlot
    source: Annotated[SavedItemSource | RetainedItemSource, Field(discriminator='kind')]


class UnequipItem(DTO):
    type: Literal['unequip_item']
    slot: EngineSlot


class SocketRune(DTO):
    type: Literal['socket_rune']
    slot: EngineSlot
    socket_index: Annotated[int, Field(ge=0, le=15)]
    rune_catalog_id: CatalogID


class InstillAmulet(DTO):
    type: Literal['instill_amulet']
    notable_node_id: NodeID
    recipe_catalog_id: CatalogID


Edit = Annotated[SetGem | SetSupports | AllocatePassives | RefundPassives | SetAscendancy |
    EquipItem | UnequipItem | SocketRune | InstillAmulet, Field(discriminator='type')]


class OwnedHelper(DTO):
    slot: EngineSlot
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)]
    availability: Literal['user_confirmed_owned']


class TransitionAction(DTO):
    slot: EngineSlot | None = None
    action: Literal['equip', 'unequip', 'apply_edit']
    saved_item_id: Annotated[int, Field(ge=1, le=1000000)] | None = None
    edit_index: Annotated[int, Field(ge=0, le=31)] | None = None
    temporary: bool
    owned_helper: bool


class EquipmentTransition(DTO):
    status: Literal['verified', 'requires_order_validation', 'no_valid_order_within_choices', 'search_budget_exhausted']
    actions: Annotated[list[TransitionAction], Field(max_length=32)]
    states_evaluated: int
    search_exhausted: bool
    optimality: Literal['fewest_actions_within_supplied_owned_choices', 'unproven'] = 'unproven'
    helper_purchase_cost: Literal[0] = 0
    scope: Literal['supplied_final_items_and_user_confirmed_owned_helpers'] = 'supplied_final_items_and_user_confirmed_owned_helpers'


class ExperimentRequest(DTO):
    base_build_id: BuildRef
    base_snapshot_digest: Digest
    tree_revision: Annotated[str, Field(pattern=r'^[0-9]+_[0-9]+$', max_length=24)]
    engine_data_commit: Annotated[str, Field(pattern=r'^[0-9a-f]{40}$')]
    target: CalculationTarget
    configuration: CalculationConfiguration | None = None
    combat_scenario: CombatScenario | None = None
    edits: Annotated[list[Edit], Field(min_length=1, max_length=32)]
    ordinary_points_available: Annotated[int, Field(ge=0, le=128)] = 0
    ascendancy_points_available: Annotated[int, Field(ge=0, le=8)] = 0
    point_budget_evidence: Literal['user_reported'] = 'user_reported'
    temporary_equipment: Annotated[list[OwnedHelper], Field(max_length=8)] = Field(default_factory=list)
    transition_state_budget: Annotated[int, Field(ge=1, le=64)] = 32
    mode: Literal['dry_run'] = 'dry_run'
    persist_decision: bool = False

    @model_validator(mode='after')
    def consistent(self) -> Self:
        for edit in self.edits:
            for field in ('node_ids', 'support_gem_ids', 'allocate_node_ids', 'refund_node_ids'):
                values=getattr(edit, field, [])
                if len(values)!=len(set(values)):
                    raise ValueError('duplicate_edit_entity')
            if isinstance(edit, SetSupports) and len(edit.support_gem_ids)>edit.observed_socket_capacity:
                raise ValueError('support_socket_capacity_exceeded')
            if isinstance(edit, AllocatePassives):
                choices=[c.node_id for c in edit.attribute_choices]
                if len(choices)!=len(set(choices)) or not set(choices)<=set(edit.node_ids):
                    raise ValueError('invalid_attribute_choices')
        return self


class EditFailure(DTO):
    edit_index: Annotated[int, Field(ge=0, le=31)]
    code: Literal['entity_not_found', 'invalid_level', 'support_incompatible', 'socket_capacity',
        'graph_disconnected', 'point_budget', 'wrong_point_pool', 'attribute_choice_required',
        'rune_incompatible', 'instill_recipe_unverified', 'unsupported_node_rule', 'immutable_source_mismatch']


class EditAudit(DTO):
    edit_index: int
    type: Annotated[str, Field(max_length=32)]
    status: Literal['applied_to_private_clone']


class ExperimentAudit(DTO):
    status: Literal['valid_changeset', 'rejected_atomically']
    failures: Annotated[list[EditFailure], Field(max_length=32)]
    applied_edits: Annotated[list[EditAudit], Field(max_length=32)]
    ordinary_points_delta: int = 0
    ascendancy_points_delta: int = 0
    base_unchanged: Literal[True] = True
    equipment_transition: EquipmentTransition | None = None
    transition_validation: Literal['requires_order_validation', 'no_equipment_transition', 'verified'] = 'requires_order_validation'


class ExperimentResult(DTO):
    experiment_id: ExperimentID
    base_build_id: BuildRef
    base_snapshot_digest: Digest
    plan_digest: Digest
    audit: ExperimentAudit
    audit_truncated: bool = False
    edit_count: int
    calculation_id: Annotated[str, Field(pattern=r'^calc_[0-9a-f]{32}$')]
    calculation_expires_at_epoch: int
    baseline_metrics: Annotated[list[PlayerStat], Field(max_length=8)]
    candidate_metrics: Annotated[list[PlayerStat], Field(max_length=8)]
    deltas: Annotated[list[PlayerStat], Field(max_length=8)]
    subject: SubjectBinding | None = None
    candidate_validation: Literal['pass', 'fail', 'indeterminate', 'not_evaluated']
    certified: bool
    artifact_digest: Digest
    decision_persisted: bool
    state: Literal['proposed'] = 'proposed'
    changes_applied_to_game: Literal[False] = False
