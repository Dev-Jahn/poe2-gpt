"""Explicit, discovered calculation identities shared across every candidate."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .builds import DTO
from .profiles import SkillInstanceID, Digest

EffectID = Annotated[str, Field(pattern=r'^[A-Za-z0-9_]+$', max_length=120)]
Actor = Literal['player', 'minion', 'hollow_image', 'spirit_vessel']


class CalculationTarget(DTO):
    skill_instance_id: SkillInstanceID
    actor_ref: Actor
    component_ref: EffectID | None = None
    weapon_set_id: Literal[1, 2]
    aggregation: Literal['single_skill', 'component_breakdown'] = 'single_skill'


class EvaluatedSubject(DTO):
    skill_instance_id: SkillInstanceID | None = None
    skill_id: EffectID
    actor_ref: Actor
    component_ref: EffectID
    weapon_set_id: Literal[1, 2]


class SubjectBinding(DTO):
    saved: EvaluatedSubject | None = None
    requested: CalculationTarget | None = None
    evaluated: EvaluatedSubject | None = None
    status: Literal['saved_default', 'matched', 'unavailable']
    reason: Literal['instance_not_found', 'instance_disabled', 'ambiguous_component',
        'component_not_found', 'actor_not_supported', 'actor_mismatch', 'eligibility_changed'] | None = None
    scenario_digest: Digest
    next_action: Literal['inspect_skill_instances', 'choose_component', 'supply_supported_actor', 'repair_skill_eligibility'] | None = None

    @model_validator(mode='after')
    def coherent(self) -> Self:
        if self.status=='matched':
            if self.requested is None or self.evaluated is None:
                raise ValueError('matched_subject_requires_identities')
            if (self.requested.skill_instance_id!=self.evaluated.skill_instance_id
                    or self.requested.actor_ref!=self.evaluated.actor_ref
                    or self.requested.weapon_set_id!=self.evaluated.weapon_set_id
                    or (self.requested.component_ref is not None and self.requested.component_ref!=self.evaluated.component_ref)):
                raise ValueError('evaluated_subject_mismatch')
        if self.status=='unavailable' and self.evaluated is not None:
            raise ValueError('unavailable_subject_cannot_be_evaluated')
        if self.status=='saved_default' and self.requested is not None:
            raise ValueError('explicit_target_cannot_fall_back_to_saved_default')
        return self
