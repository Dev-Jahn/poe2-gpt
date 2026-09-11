"""Interval ordering and correction BOM arithmetic; no invented game rolls."""
import pytest
from poe2_companion.builds import PlayerStat,tool_json_bytes
from poe2_companion.engine_models import MechanicResult
from poe2_companion.experiment_models import EquipItem
from poe2_companion.item_transforms import TransformRequest,analyze as transform
from poe2_companion.plan_dependencies import DependencyRequest,analyze as dependencies
from poe2_companion.workflow_store import DecisionStore,WorkflowError
from test_workflow_purchases import document


def glove(index):
    doc=document(index,2,False,100)
    doc.calculation.result=doc.calculation.result.model_copy(deep=True)
    doc.request.edits=[EquipItem(type='equip_item',slot='gloves',source={'kind':'saved_item','saved_item_id':index})]
    doc.calculation.baseline.stats=[PlayerStat(name='EnergyShield',value=100)]
    doc.calculation.result.stats=[PlayerStat(name='EnergyShield',value=1000)]
    doc.calculation.result.mechanics=[MechanicResult(mechanic='stonefist',status='unsupported',metrics=[],required_inputs=['transformed_glove_data'])]
    return doc


def test_unknown_transform_has_only_conditional_intervals_and_exact_variant_links():
    store=DecisionStore('m');original=glove(1);actual=glove(2)
    actual.calculation.result.mechanics[0]=MechanicResult(mechanic='stonefist',status='calculated',
        metrics=[{'name':'already_transformed','value':1}],required_inputs=[])
    store.save('alice',original);store.save('alice',actual)
    query=TransformRequest(original_experiment_id=original.experiment_id,effective_experiment_ids=[actual.experiment_id],
        association_evidence='user_reported_original_effective_relationship',unrolled_envelopes=[
            {'metric':'EnergyShield','lower':101.,'upper':200.,'evidence':'user_supplied_hypothetical_character_metric_envelope'}])
    result=transform(query,store,'alice')
    assert result.original_calculation_status=='unresolved_transformation'
    assert result.effective_variants[0].native_transformed_rolls_loaded
    assert result.all_supplied_bounds_dominate_baseline
    assert not result.original_values_eligible_for_ranking
    assert result.unrolled_metric_intervals[0].midpoint_estimate is None
    assert not result.unrolled_metric_intervals[0].game_feasible_bounds_verified
    query.unrolled_envelopes[0].lower=99.
    assert not transform(query,store,'alice').all_supplied_bounds_dominate_baseline
    with pytest.raises(WorkflowError):transform(query,store,'bob')


def test_joint_belt_loss_outputs_correction_requirements_not_only_item_delta():
    store=DecisionStore('m');doc=document(1,2,False,100)
    doc.calculation.result=doc.calculation.result.model_copy(deep=True)
    doc.request.edits=[EquipItem(type='equip_item',slot='belt',source={'kind':'saved_item','saved_item_id':1})]
    doc.calculation.baseline.stats=[PlayerStat(name=n,value=v) for n,v in {'Str':100,'FireResist':75,'SpiritUnreserved':20,'EnergyShieldRegen':50}.items()]
    doc.calculation.result.stats=[PlayerStat(name=n,value=v) for n,v in {'Str':60,'FireResist':45,'SpiritUnreserved':-10,'EnergyShieldRegen':0}.items()]
    attrs=lambda s:{'strength':float(s),'dexterity':0.,'intelligence':0.}
    from poe2_companion.requirements import RequirementBreakdown
    doc.calculation.result.requirements=RequirementBreakdown(available=attrs(60),engine_required=attrs(80),
        equipment_maximum=attrs(80),native_gem_maximum=attrs(0),support_sum=attrs(0),sources=[
            {'kind':'equipment','base_attributes':attrs(80),'modified_attributes':attrs(80),'satisfying_attributes':attrs(60),
            'attribute_requirements_ignored':False,'satisfied':False}])
    store.save('alice',doc)
    result=dependencies(DependencyRequest(experiment_id=doc.experiment_id,floors=[{'metric':'FireResist','minimum':75.}]),store,'alice')
    bill={r.metric:r.minimum_additional for r in result.corrective_bill}
    assert bill=={'Str':20.,'FireResist':30.,'SpiritUnreserved':10.}
    assert 'EnergyShieldRegen' in {r.metric for r in result.lost_supplies}
    assert all(r.resolved_purchase_cost is None for r in result.corrective_bill)
    assert tool_json_bytes(result)<=8192 and not result.complete_package_cost_known
