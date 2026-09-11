"""Click order over exactly the requested nodes in the full pinned graph."""
from collections import deque
from typing import Annotated,Literal
from pydantic import Field
from .builds import DTO
from .catalog_models import BuildRef,NodeID,NativeCatalog
from .engine_models import ENGINE_DATA_COMMIT,EngineError


class TreeAction(DTO):
    edit_index: Annotated[int,Field(ge=0,le=31)]
    action: Literal['allocate','refund']
    node_ids: Annotated[list[NodeID],Field(min_length=1,max_length=64)]
    allocation_mode: Literal[0,1,2] = 0


class PassiveOrderRequest(DTO):
    build_id: BuildRef
    tree_revision: Annotated[str,Field(max_length=24)]
    actions: Annotated[list[TreeAction],Field(min_length=1,max_length=64)]


class PassiveOrderResult(DTO):
    build_id: BuildRef
    tree_revision: str
    engine_data_commit: str
    status: Literal['verified','unsupported_node_rule','no_order_within_requested_nodes']
    actions: Annotated[list[TreeAction],Field(max_length=64)]
    extra_nodes_added: Literal[False] = False
    point_budget_requires_joint_experiment: Literal[True] = True


def order(catalog: NativeCatalog,request: PassiveOrderRequest) -> PassiveOrderResult:
    if request.tree_revision!=catalog.tree_version: raise EngineError('engine_version_mismatch')
    nodes={n.node_id:n for n in catalog.nodes}
    allocated={n.node_id for n in catalog.nodes if n.allocated}
    modes={n.node_id:n.allocation_mode for n in catalog.nodes}
    roots={catalog.class_start_node_id}
    if catalog.ascendancy_start_node_id is not None:roots.add(catalog.ascendancy_start_node_id)
    value=PassiveOrderResult(build_id=request.build_id,tree_revision=catalog.tree_version,engine_data_commit=ENGINE_DATA_COMMIT,status='verified',actions=[])
    def reachable(active: set[int],mode: int) -> set[int]:
        found=set(roots);queue=deque(roots)
        while queue:
            node=nodes[queue.popleft()]
            for adjacent in node.linked_node_ids:
                other=nodes.get(adjacent)
                if adjacent in active and adjacent not in found and other and modes[adjacent] in (0,mode) and other.ascendancy==node.ascendancy:
                    found.add(adjacent);queue.append(adjacent)
        return found
    def connected(active: set[int]) -> bool:
        reached={mode:reachable(active,mode) for mode in (0,1,2)}
        return all(identifier in reached[modes[identifier]] for identifier in active)
    wanted={identifier for action in request.actions for identifier in action.node_ids}
    if not wanted<=nodes.keys():raise EngineError('engine_invalid_request')
    if any(nodes[n].special_allocation_rule or nodes[n].type=='Mastery' for n in wanted | (allocated-roots)) or wanted & roots:
        value.status='unsupported_node_rule';return value
    if not connected(allocated):value.status='no_order_within_requested_nodes';return value
    for action in request.actions:
        pending=set(action.node_ids)
        if len(pending)!=len(action.node_ids) or (action.action=='refund' and not pending<=allocated) or (action.action=='allocate' and pending & allocated):
            raise EngineError('engine_invalid_request')
        ordered=[]
        while pending:
            found=None
            for identifier in sorted(pending):
                if action.action=='refund':
                    valid=connected(allocated-{identifier})
                else:
                    mode=action.allocation_mode
                    modes[identifier]=mode
                    valid=connected(allocated | {identifier})
                if valid:found=identifier;break
            if found is None:
                value.status='no_order_within_requested_nodes';value.actions=[];return value
            if action.action=='refund':allocated.remove(found)
            else:allocated.add(found)
            ordered.append(found);pending.remove(found)
        value.actions.append(action.model_copy(update={'node_ids':ordered}))
    return value
