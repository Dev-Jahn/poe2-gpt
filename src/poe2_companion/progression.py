"""Milestones combine pinned native gem requirements with explicit user evidence."""
from __future__ import annotations
from typing import Annotated, Literal, TYPE_CHECKING
from pydantic import Field, model_validator
from .builds import DTO, bounded_dto
from .profiles import BuildRef, Digest, SkillInstanceID, ProfileRequest
from .catalog_models import CatalogRequest
from .observations import ObservationID, ObservationValue, keys, LevelObservation, PointObservation, UnlockObservation, GemObservation
from .workflow_store import WorkflowError

if TYPE_CHECKING:
    from .engine import EngineClient
    from .workflow_store import DecisionStore

Unlock = Literal['amulet_instilling', 'endgame_maps', 'ascendancy_trial', 'advanced_gem_sockets']


class GemGoal(DTO):
    skill_instance_id: SkillInstanceID
    gem_catalog_id: Annotated[str, Field(min_length=1, max_length=160)]
    native_level: Annotated[int, Field(ge=1, le=100)]
    support_socket_capacity: Annotated[int, Field(ge=0, le=10)] = 0
    acquisition: Literal['level_existing_gem', 'replace_with_purchased_gem'] = 'level_existing_gem'
    purchased_gem_observed_capacity: Annotated[int, Field(ge=0, le=10)] | None = None


class Milestone(DTO):
    character_level: Annotated[int, Field(ge=1, le=100)]
    ordinary_points_spent: Annotated[int, Field(ge=0, le=128)] = 0
    ascendancy_points_spent: Annotated[int, Field(ge=0, le=8)] = 0
    required_unlocks: Annotated[list[Unlock], Field(max_length=4)] = Field(default_factory=list)
    gem_goals: Annotated[list[GemGoal], Field(max_length=3)] = Field(default_factory=list)


class ProgressionRequest(DTO):
    build_id: BuildRef
    snapshot_digest: Digest
    observation_ids: Annotated[list[ObservationID], Field(max_length=8)] = Field(default_factory=list)
    milestones: Annotated[list[Milestone], Field(min_length=1, max_length=4)]

    @model_validator(mode='after')
    def ordered(self):
        levels = [m.character_level for m in self.milestones]
        if levels != sorted(set(levels)): raise ValueError('milestones_require_distinct_ascending_levels')
        return self


class GemReadiness(DTO):
    skill_instance_id: SkillInstanceID
    name: str
    catalog_id: str
    native_level: int
    character_level_required: int
    strength_required: float
    dexterity_required: float
    intelligence_required: float
    socket_capacity_evidence: Literal['user_reported_sufficient', 'user_reported_insufficient', 'unknown']
    requirements_scope: Literal['native_gem_before_build_modifiers'] = 'native_gem_before_build_modifiers'
    effective_level_used_for_requirements: Literal[False] = False


class MilestoneResult(DTO):
    character_level: int
    ordinary_points_available_before_step: int | None
    ascendancy_points_available_before_step: int | None
    ordinary_points_remaining: int | None
    ascendancy_points_remaining: int | None
    unmet_or_unknown: Annotated[list[str], Field(max_length=24)]
    gems: Annotated[list[GemReadiness], Field(max_length=3)]
    status: Literal['prerequisites_accounted_for', 'blocked_or_requires_evidence']
    joint_native_experiment_required: Literal[True] = True


class ProgressionPlan(DTO):
    build_id: BuildRef
    snapshot_digest: Digest
    saved_level: int
    reported_level: int | None
    reported_state_confirmed_by_source: Literal[False] = False
    unknown_quest_rewards_assumed_complete: Literal[False] = False
    automatic_ascendancy_points_from_leveling: Literal[False] = False
    milestones: Annotated[list[MilestoneResult], Field(max_length=4)]
    next_action: Literal['verify_unknown_prerequisites_then_evaluate_joint_changeset'] = 'verify_unknown_prerequisites_then_evaluate_joint_changeset'


async def plan(request: ProgressionRequest, engine: EngineClient, store: DecisionStore, owner: str) -> ProgressionPlan:
    from .catalog_models import CatalogPage
    wanted = sorted({g.skill_instance_id for m in request.milestones for g in m.gem_goals})
    profile = await engine.profile(ProfileRequest(build_id=request.build_id, skill_instance_ids=wanted, limit=12))
    if profile.snapshot_digest != request.snapshot_digest: raise WorkflowError('progression_snapshot_mismatch')
    skills = {s.skill_instance_id:s for s in profile.skill_instances}
    next_offset = profile.next_offset
    while next_offset is not None and not set(wanted) <= set(skills):
        more = await engine.profile(ProfileRequest(build_id=request.build_id, skill_instance_ids=wanted, offset=next_offset, limit=12))
        skills.update((s.skill_instance_id,s) for s in more.skill_instances)
        next_offset = more.next_offset
    observations: dict[str, ObservationValue] = {}
    for identifier in request.observation_ids:
        row = store.get_observation(owner, identifier)
        if (row.request.base_build_id,row.request.base_snapshot_digest) != (request.build_id,request.snapshot_digest):
            raise WorkflowError('observation_snapshot_mismatch')
        for key,value in keys(row).items():
            if key in observations and observations[key] != value: raise WorkflowError('conflicting_progression_observations')
            observations[key] = value
    reported = observations.get('character_level')
    reported_level = reported.level if isinstance(reported,LevelObservation) else None
    level = reported_level if reported_level is not None else profile.metadata.level
    points = observations.get('available_points')
    ordinary = points.ordinary if isinstance(points,PointObservation) else None
    ascendancy = points.ascendancy if isinstance(points,PointObservation) else None
    results = []
    earlier_blocked = False
    for milestone in request.milestones:
        if milestone.character_level < level: raise WorkflowError('milestone_precedes_reported_level')
        # Native level budget awards one ordinary point per level. Unknown quest
        # rewards add zero; they never create ascendancy or assumed unlocks.
        if ordinary is not None: ordinary += milestone.character_level - level
        level = milestone.character_level
        problems = ['previous_milestone_requires_resolution'] if earlier_blocked else []
        for unlock in milestone.required_unlocks:
            evidence = observations.get('progression_unlock:' + unlock)
            if not isinstance(evidence,UnlockObservation): problems.append('unlock_unknown:' + unlock)
            elif not evidence.unlocked: problems.append('unlock_required:' + unlock)
        if ordinary is None: problems.append('ordinary_points_unknown')
        elif ordinary < milestone.ordinary_points_spent: problems.append('ordinary_points_insufficient')
        if milestone.ascendancy_points_spent:
            if ascendancy is None: problems.append('ascendancy_points_unknown')
            elif ascendancy < milestone.ascendancy_points_spent: problems.append('ascendancy_points_insufficient')
        gems = []
        for goal in milestone.gem_goals:
            source = skills.get(goal.skill_instance_id)
            if source is None or source.origin != 'socketed': raise WorkflowError('gem_instance_not_socketed')
            catalog = await engine.static_request('/catalog',CatalogRequest(build_id=request.build_id,
                entity_type='gem',catalog_id=goal.gem_catalog_id,native_level=goal.native_level,level_limit=1),CatalogPage)
            if len(catalog.gems) != 1: raise WorkflowError('gem_catalog_identity_unavailable')
            definition = catalog.gems[0]
            if definition.skill_id != source.skill_id or definition.support: raise WorkflowError('gem_catalog_identity_mismatch')
            native = next((g for g in definition.levels if g.native_level == goal.native_level),None)
            if native is None: raise WorkflowError('native_gem_level_unavailable')
            if native.character_level_required > level: problems.append('gem_level_requirement:' + goal.skill_instance_id)
            observed = observations.get('gem_state:' + goal.skill_instance_id)
            capacity: Literal['user_reported_sufficient','user_reported_insufficient','unknown'] = 'unknown'
            if goal.acquisition == 'replace_with_purchased_gem':
                if goal.purchased_gem_observed_capacity is not None:
                    capacity = 'user_reported_sufficient' if goal.purchased_gem_observed_capacity >= goal.support_socket_capacity else 'user_reported_insufficient'
            elif isinstance(observed,GemObservation):
                capacity = 'user_reported_sufficient' if observed.socket_capacity >= goal.support_socket_capacity else 'user_reported_insufficient'
            if goal.support_socket_capacity and capacity != 'user_reported_sufficient':
                problems.append('gem_socket_capacity:' + goal.skill_instance_id)
            gems.append(GemReadiness(skill_instance_id=goal.skill_instance_id,name=definition.name,
                catalog_id=definition.catalog_id,native_level=goal.native_level,
                character_level_required=native.character_level_required,strength_required=native.strength_required,
                dexterity_required=native.dexterity_required,intelligence_required=native.intelligence_required,
                socket_capacity_evidence=capacity))
        earlier_blocked = bool(problems)
        before_ordinary,before_ascendancy = ordinary,ascendancy
        if ordinary is not None: ordinary -= milestone.ordinary_points_spent
        if ascendancy is not None: ascendancy -= milestone.ascendancy_points_spent
        results.append(MilestoneResult(character_level=level,ordinary_points_available_before_step=before_ordinary,
            ascendancy_points_available_before_step=before_ascendancy,ordinary_points_remaining=ordinary,
            ascendancy_points_remaining=ascendancy,unmet_or_unknown=problems,gems=gems,
            status='blocked_or_requires_evidence' if problems else 'prerequisites_accounted_for'))
    return bounded_dto(ProgressionPlan(build_id=request.build_id,snapshot_digest=request.snapshot_digest,
        saved_level=profile.metadata.level,reported_level=reported_level,milestones=results))
