"""Per-instance immutable calculation receipts with lossless diagnostic pages."""
import secrets
import time
from collections import OrderedDict
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .builds import DTO, MAX_TOOL_JSON_BYTES, PlayerStat
from .engine_models import EngineCalculation, EngineError, RequirementIssue, MechanicResult, MetricCoverage
from .combat_models import CombatScenarioResult
from .calculation_config import CalculationConfiguration

Section = Literal['issues', 'mechanics', 'stats', 'metric_coverage', 'deltas', 'combat_scenario', 'inputs', 'candidates']


class InputValue(DTO):
    path: str
    value: bool | float | str | None = None


class CandidateEvaluation(DTO):
    index: int
    status: Literal['eligible', 'invalid_equipment', 'unresolved_dependencies', 'constraints_not_met']
    cost: float


class InputGuidance(DTO):
    required_input: str
    route: Literal['configuration', 'combat_scenario', 'inspect_build', 'not_exposed']
    fields: list[str] = Field(default_factory=list)
    note: str


def input_guidance(names):
    aliases={'azmeri_spirit':['natural_order_spirit'], 'captured_beast_modifiers':['captured_beast_mods'],
        'refutation_buff_state':['refutation_active','refutation_ward_spent'],
        'hollow_form_channel_events':['hollow_form_attack_skill_id','hollow_form_channel_uses_per_second','hollow_form_power_charge_use_fraction']}
    events={'charge_gain_events':'external_charge_gain','charge_consumption_events':'flicker_use',
        'incoming_hit_sequence':'incoming_hit','ally_charge_events':'ally_hit','ally_presence':'ally_hit'}
    result=[]
    for name in sorted(names):
        if name in CalculationConfiguration.model_fields or name in aliases:
            result.append(InputGuidance(required_input=name,route='configuration',fields=['configuration.'+f for f in aliases.get(name,[name])],note='Explicit hypothetical input; confirm combat assumptions with the user.'))
        elif name in events:
            result.append(InputGuidance(required_input=name,route='combat_scenario',fields=['combat_scenario.events'],note='Use '+events[name]+' events. Scenario results do not certify live uptime or alter snapshot DPS.'))
        elif name=='hollow_form_socketed_skill':
            result.append(InputGuidance(required_input=name,route='inspect_build',fields=['section=skills'],note='Discover the saved active skill and support group first.'))
        else:
            result.append(InputGuidance(required_input=name,route='not_exposed',note='No public input fully resolves this mechanic; retain its limitation.'))
    return result


class DiagnosticRequest(DTO):
    calculation_id: Annotated[str, Field(pattern=r"^calc_[0-9a-f]{32}$")]
    target: Literal["baseline", "result"] = "baseline"
    section: Section = "issues"
    candidate_index: Annotated[int, Field(ge=0, le=63)] | None = None
    offset: Annotated[int, Field(ge=0, le=100000)] = 0
    limit: Annotated[int, Field(ge=1, le=20)] = 10

    @model_validator(mode='after')
    def coherent(self):
        if self.candidate_index is not None and self.section in {'deltas', 'inputs', 'candidates'}:
            raise ValueError('candidate_selector_requires_snapshot_section')
        return self


class DiagnosticPage(DTO):
    calculation_id: str
    build_id: str
    target: Literal["baseline", "result"]
    section: Section
    candidate_index: int | None = None
    total: int
    next_offset: int | None = None
    issues: list[RequirementIssue] = Field(default_factory=list)
    mechanics: list[MechanicResult] = Field(default_factory=list)
    stats: list[PlayerStat] = Field(default_factory=list)
    metric_coverage: list[MetricCoverage] = Field(default_factory=list)
    deltas: list[PlayerStat] = Field(default_factory=list)
    combat_scenario: list[CombatScenarioResult] = Field(default_factory=list)
    inputs: list[InputValue] = Field(default_factory=list)
    candidates: list[CandidateEvaluation] = Field(default_factory=list)
    input_guidance: list[InputGuidance] = Field(default_factory=list)
    expires_at_epoch: int


class CalculationReceipts:
    """Opaque IDs never cross instances. Bounded RAM, expiry and explicit misses."""
    def __init__(self, capacity=64, ttl=3600):
        self.rows = OrderedDict()
        self.capacity, self.ttl = capacity, ttl

    def retain(self, calculation: EngineCalculation, request=None, candidates=None, evaluations=None):
        now = int(time.time())
        for key, row in list(self.rows.items()):
            if row[1] <= now:
                self.rows.pop(key)
        calculation.calculation_id = 'calc_' + secrets.token_hex(16)
        calculation.diagnostics_expires_at_epoch = now + self.ttl
        inputs=[]
        def flatten(value, path):
            if isinstance(value, dict):
                for key, child in value.items(): flatten(child, path+'.'+key)
            elif isinstance(value, list):
                for index, child in enumerate(value): flatten(child, path+'.'+str(index))
            else: inputs.append(InputValue(path=path, value=value))
        for field in ('configuration', 'combat_scenario'):
            value=getattr(request, field, None)
            if value is not None: flatten(value.model_dump(exclude_none=True), field)
        snapshots=[s.model_copy(deep=True) for s in candidates or []]
        size=len(calculation.model_dump_json().encode())+sum(len(s.model_dump_json().encode()) for s in snapshots)
        self.rows[calculation.calculation_id] = (calculation.model_copy(deep=True), now + self.ttl,
            inputs, snapshots, [e.model_copy(deep=True) for e in evaluations or []], size)
        while len(self.rows) > self.capacity or (len(self.rows)>1 and sum(r[5] for r in self.rows.values())>32*1024*1024):
            self.rows.popitem(last=False)
        return calculation

    def page(self, request: DiagnosticRequest):
        row = self.rows.get(request.calculation_id)
        if row is None or row[1] <= time.time():
            raise EngineError('calculation_expired_or_unavailable')
        calculation, expiry, inputs, candidates, evaluations, _ = row
        snapshot = getattr(calculation, request.target)
        if request.candidate_index is not None:
            if request.candidate_index>=len(candidates):
                raise EngineError('calculation_target_unavailable')
            snapshot=candidates[request.candidate_index]
        if snapshot is None and request.section not in {'deltas', 'inputs', 'candidates'}:
            raise EngineError('calculation_target_unavailable')
        if request.section=='inputs': records=inputs
        elif request.section=='candidates': records=evaluations
        elif request.section=='deltas': records=calculation.deltas
        elif request.section=='combat_scenario': records=[snapshot.combat_scenario] if snapshot.combat_scenario else []
        else: records=getattr(snapshot, request.section)
        selected = [r.model_copy(deep=True) for r in records[request.offset:request.offset + request.limit]]
        while True:
            end = request.offset + len(selected)
            page = DiagnosticPage(calculation_id=request.calculation_id, build_id=calculation.build_id,
                target=request.target, section=request.section, candidate_index=request.candidate_index, total=len(records),
                next_offset=end if end < len(records) else None, expires_at_epoch=expiry,
                input_guidance=input_guidance({n for m in selected for n in m.required_inputs}) if request.section=='mechanics' else [],
                **{str(request.section): selected})
            if len(page.model_dump_json().encode()) <= MAX_TOOL_JSON_BYTES:
                return page
            if len(selected) <= 1:
                raise EngineError('engine_protocol_error')
            selected.pop()
