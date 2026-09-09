import pytest

from poe2_companion.diagnostics import CalculationReceipts, DiagnosticRequest
from poe2_companion.engine import bounded_engine_dto
from poe2_companion.engine_models import EngineCalculation, EngineSnapshot, RequirementIssue, EngineError

BID='bld_'+'1'*32


def test_complete_immutable_diagnostic_pages_and_isolation():
    issues=[RequirementIssue(code='unparsed_passive',passive_node_id=i) for i in range(300)]
    snapshot=EngineSnapshot(stats=[],equipped=[],issues=issues,issue_count=300,
        validation='indeterminate',active_weapon_set=1,main_skill_group=0)
    calc=EngineCalculation(build_id=BID,calculated_at_epoch=0,baseline=snapshot)
    receipts=CalculationReceipts()
    public=bounded_engine_dto(receipts.retain(calc))
    assert public.baseline.issues_truncated and len(public.model_dump_json().encode())<=8192
    public.baseline.issues.clear()
    offset, recovered = 0, []
    while offset is not None:
        page=receipts.page(DiagnosticRequest(calculation_id=calc.calculation_id,offset=offset))
        recovered.extend(i.passive_node_id for i in page.issues)
        offset=page.next_offset
    assert recovered==list(range(300))
    page=receipts.page(DiagnosticRequest(calculation_id=calc.calculation_id))
    page.issues[0].passive_node_id=999
    assert receipts.page(DiagnosticRequest(calculation_id=calc.calculation_id)).issues[0].passive_node_id==0
    with pytest.raises(EngineError,match='calculation_expired_or_unavailable'):
        CalculationReceipts().page(DiagnosticRequest(calculation_id=calc.calculation_id))


def test_all_sections_candidate_details_and_input_recovery():
    from poe2_companion.engine_models import EngineRequest, MechanicResult
    from poe2_companion.builds import STAT_NAMES, PlayerStat
    from poe2_companion.diagnostics import CandidateEvaluation
    from poe2_companion.combat_models import CombatScenarioResult
    stats=[PlayerStat(name=name,value=123.456) for name in sorted(STAT_NAMES)]
    snapshot=EngineSnapshot(stats=stats,equipped=[],issues=[],issue_count=0,validation='indeterminate',active_weapon_set=1,main_skill_group=0,
        mechanics=[MechanicResult(mechanic='leech_recovery',status='partial',required_inputs=['leech_recovery_uptime','companion_skill_rotation'])],
        combat_scenario=CombatScenarioResult(status='calculated',horizon_seconds=10,gain_roll_model='independent_nonrecursive_per_event',assumptions=[]))
    calc=EngineCalculation(build_id=BID,calculated_at_epoch=0,baseline=snapshot,deltas=stats)
    request=EngineRequest(build_id=BID,configuration={'refutation_active':False,'refutation_ward_spent':0.0})
    receipts=CalculationReceipts()
    receipts.retain(calc,request,[snapshot],[CandidateEvaluation(index=0,status='unresolved_dependencies',cost=2)])
    def page(section,**kwargs): return receipts.page(DiagnosticRequest(calculation_id=calc.calculation_id,section=section,**kwargs))
    for section in ('stats','deltas'):
        offset,recovered=0,[]
        while offset is not None:
            result=page(section,offset=offset)
            assert len(result.model_dump_json().encode())<=8192
            recovered.extend(getattr(result,section));offset=result.next_offset
        assert recovered==stats
    assert page('combat_scenario').combat_scenario==[snapshot.combat_scenario]
    assert {v.path:v.value for v in page('inputs').inputs}=={'configuration.refutation_active':False,'configuration.refutation_ward_spent':0.0}
    assert page('candidates').candidates[0].status=='unresolved_dependencies'
    details=page('mechanics',candidate_index=0)
    assert {g.required_input:g.route for g in details.input_guidance}=={'leech_recovery_uptime':'configuration','companion_skill_rotation':'not_exposed'}
    with pytest.raises(EngineError,match='calculation_target_unavailable'): page('issues',candidate_index=1)


def test_dense_requested_metrics_are_never_lost_from_summary():
    from test_game_terms import dense_engine_result
    value=dense_engine_result(fully_configured=True)
    requested=[s.name for s in value.calculation.baseline.stats if any(k in s.name for k in ('MaximumHitTaken','Regen','Leech','OverCap'))][:16]
    value.calculation.requested_metrics=requested
    result=bounded_engine_dto(CalculationReceipts().retain(value.calculation))
    assert len(result.model_dump_json().encode())<=8192
    for side in (result.baseline,result.result):
        assert set(requested)<={s.name for s in side.stats}
    assert set(requested)<={s.name for s in result.deltas}
