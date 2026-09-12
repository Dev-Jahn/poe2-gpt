"""Typed user evidence is an overlay, never a mutation of an imported build."""
from __future__ import annotations
import time
import secrets
from typing import Annotated, Literal, Self, TYPE_CHECKING
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto
from .profiles import BuildRef, Digest, SkillInstanceID

if TYPE_CHECKING:
    from .workflow_store import DecisionStore

ObservationID=Annotated[str,Field(pattern=r'^obs_[0-9a-f]{32}$')]


class LevelObservation(DTO):
    kind: Literal['character_level']
    level: Annotated[int,Field(ge=1,le=100)]


class PointObservation(DTO):
    kind: Literal['available_points']
    ordinary: Annotated[int,Field(ge=0,le=128)]
    ascendancy: Annotated[int,Field(ge=0,le=8)]


class UnlockObservation(DTO):
    kind: Literal['progression_unlock']
    unlock: Literal['amulet_instilling','endgame_maps','ascendancy_trial','advanced_gem_sockets']
    unlocked: bool


class GemObservation(DTO):
    kind: Literal['gem_state']
    skill_instance_id: SkillInstanceID
    native_level: Annotated[int,Field(ge=1,le=100)]
    socket_capacity: Annotated[int,Field(ge=0,le=10)]


class ResourceObservation(DTO):
    kind: Literal['resource_outcome']
    resource: Literal['life','mana','energy_shield']
    maximum: Annotated[float,Field(ge=0,le=1e12,allow_inf_nan=False)]
    minimum_during_encounter: Annotated[float,Field(ge=0,le=1e12,allow_inf_nan=False)]
    encounter: Literal['mapping','ritual','boss_no_adds','other']
    outcome: Literal['stable','depleted','died','unknown']

    @model_validator(mode='after')
    def capacity(self) -> Self:
        if self.minimum_during_encounter>self.maximum: raise ValueError('observation_exceeds_capacity')
        return self


ObservationValue=Annotated[LevelObservation|PointObservation|UnlockObservation|GemObservation|ResourceObservation,Field(discriminator='kind')]


class ObservationRequest(DTO):
    base_build_id: BuildRef
    base_snapshot_digest: Digest
    observed_at_epoch: Annotated[int,Field(ge=0,le=100000000000)]
    values: Annotated[list[ObservationValue],Field(min_length=1,max_length=16)]
    related_experiment_id: Annotated[str,Field(pattern=r'^exp_[0-9a-f]{32}$')] | None = None
    persist_observation: bool = False


class ObservationRecord(DTO):
    observation_id: ObservationID
    request: ObservationRequest
    recorded_at_epoch: int
    expires_at_epoch: int
    status: Literal['pending_source_confirmation'] = 'pending_source_confirmation'
    evidence: Literal['user_reported'] = 'user_reported'
    engine_verified: Literal[False] = False
    original_snapshot_modified: Literal[False] = False


class ObservationPageRequest(DTO):
    observation_ids: Annotated[list[ObservationID],Field(min_length=1,max_length=8)]
    offset: Annotated[int,Field(ge=0,le=8)] = 0
    limit: Annotated[int,Field(ge=1,le=4)] = 2


class DeleteObservationRequest(DTO):
    observation_id: ObservationID


class ObservationPage(DTO):
    records: Annotated[list[ObservationRecord],Field(max_length=8)]
    conflicting_fields: Annotated[list[Annotated[str,Field(max_length=160)]],Field(max_length=32)]
    overlay_applied_to_engine: Literal[False] = False
    next_action: Literal['fetch_character_and_compare_source','clarify_conflicting_observations']
    total: int
    next_offset: int | None = None


def keys(record: ObservationRecord) -> dict[str,ObservationValue]:
    result={}
    for value in record.request.values:
        suffix=value.unlock if isinstance(value,UnlockObservation) else value.skill_instance_id if isinstance(value,GemObservation) else value.resource+':'+value.encounter if isinstance(value,ResourceObservation) else ''
        result[value.kind+(':'+suffix if suffix else '')]=value
    return result


def record(store: DecisionStore, owner: str, request: ObservationRequest) -> ObservationRecord:
    from .workflow_store import WorkflowError
    now=int(time.time())
    if request.observed_at_epoch>now+300: raise WorkflowError('observation_timestamp_in_future')
    plan=None
    if request.related_experiment_id:
        plan=store.get(owner,request.related_experiment_id)
        if plan.request.base_build_id!=request.base_build_id or plan.request.base_snapshot_digest!=request.base_snapshot_digest:
            raise WorkflowError('observation_plan_revision_mismatch')
    value=ObservationRecord(observation_id='obs_'+secrets.token_hex(16),request=request,recorded_at_epoch=now,
        expires_at_epoch=now+(90*86400 if request.persist_observation else 3600))
    if len(keys(value))!=len(request.values): raise WorkflowError('duplicate_observation_field')
    bounded_dto(value)
    store.save_observation(owner,value)
    if plan is not None:
        if len(plan.observation_ids)>=32:
            store.delete_observation(owner,value.observation_id)
            raise WorkflowError('plan_observation_limit_exceeded')
        previous=plan.revision
        plan.observation_ids.append(value.observation_id);plan.revision+=1
        if (plan.state in {'applied','partially_applied'} and plan.last_reported_application_at_epoch is not None
                and request.observed_at_epoch>=plan.last_reported_application_at_epoch
                and any(isinstance(v,ResourceObservation) for v in request.values)):
            # This is a user-observed outcome, not upstream/live confirmation.
            plan.state='observed'
        try: store.save(owner,plan,expected_revision=previous)
        except Exception:
            store.delete_observation(owner,value.observation_id)
            raise
    return value


def page(store: DecisionStore, owner: str, request: ObservationPageRequest) -> ObservationPage:
    from .workflow_store import WorkflowError
    rows=[store.get_observation(owner,identifier) for identifier in request.observation_ids]
    if len({(row.request.base_build_id,row.request.base_snapshot_digest) for row in rows})>1:
        raise WorkflowError('observation_snapshot_mismatch')
    prior: dict[str,ObservationValue] = {}
    conflicts: set[str] = set()
    for row in rows:
        for key,value in keys(row).items():
            if key in prior and value!=prior[key]:conflicts.add(key)
            prior[key]=value
    end=request.offset+request.limit
    result=ObservationPage(records=rows[request.offset:end],conflicting_fields=sorted(conflicts),total=len(rows),
        next_offset=end if end<len(rows) else None,
        next_action='clarify_conflicting_observations' if conflicts else 'fetch_character_and_compare_source')
    from .builds import BuildError
    while True:
        try:return bounded_dto(result)
        except BuildError:
            if len(result.records)<=1:raise
            result.records.pop();result.next_offset=request.offset+len(result.records)
