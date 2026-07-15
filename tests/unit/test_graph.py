from __future__ import annotations

import pytest
from pydantic import ValidationError

from quantforge.domain.models import ValidationStatus
from quantforge.evidence.graph import (
    ClaimGraph,
    ClaimGraphSnapshot,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
)
from quantforge.workflow.demo import run_demo

HASH = "a" * 64


def _evidence_node(node_id: str) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        node_type=NodeType.EVIDENCE,
        evidence_sha256=HASH,
        evidence_validation_status=ValidationStatus.VALIDATED,
    )


def test_claim_graph_traceability_and_roundtrip() -> None:
    graph = ClaimGraph()
    graph.add_node(_evidence_node("evidence_source"))
    graph.add_node(GraphNode(node_id="claim_parent", node_type=NodeType.CLAIM))
    graph.add_node(
        GraphNode(node_id="claim_final", node_type=NodeType.CLAIM, substantive_final_claim=True)
    )
    graph.add_edge(
        GraphEdge(
            edge_id="edge_support",
            source_id="evidence_source",
            target_id="claim_parent",
            edge_type=EdgeType.SUPPORTS,
        )
    )
    graph.add_edge(
        GraphEdge(
            edge_id="edge_derived",
            source_id="claim_final",
            target_id="claim_parent",
            edge_type=EdgeType.DERIVED_FROM,
        )
    )
    graph.validate_final_claim_traceability()
    assert ClaimGraph.from_snapshot(graph.snapshot()).snapshot() == graph.snapshot()


def test_claim_graph_rejects_untraceable_and_invalid_mutations() -> None:
    graph = ClaimGraph()
    node = GraphNode(node_id="claim_final", node_type=NodeType.CLAIM, substantive_final_claim=True)
    graph.add_node(node)
    with pytest.raises(ValueError, match="already exists"):
        graph.add_node(node)
    with pytest.raises(ValueError, match="lacks evidence"):
        graph.validate_final_claim_traceability()
    bad = GraphEdge(
        edge_id="edge_bad",
        source_id="claim_final",
        target_id="claim_missing",
        edge_type=EdgeType.QUALIFIES,
    )
    with pytest.raises(ValueError, match="endpoint"):
        graph.add_edge(bad)
    graph.add_node(GraphNode(node_id="claim_other", node_type=NodeType.CLAIM))
    with pytest.raises(ValueError, match="node-type"):
        graph.add_edge(
            GraphEdge(
                edge_id="edge_type_invalid",
                source_id="claim_final",
                target_id="claim_other",
                edge_type=EdgeType.SUPPORTS,
            )
        )


def test_claim_graph_rejects_duplicate_edge_and_corrupt_snapshots() -> None:
    graph = ClaimGraph()
    graph.add_node(GraphNode(node_id="claim_node", node_type=NodeType.CLAIM))
    graph.add_node(GraphNode(node_id="claim_parent", node_type=NodeType.CLAIM))
    edge = GraphEdge(
        edge_id="edge_derived",
        source_id="claim_node",
        target_id="claim_parent",
        edge_type=EdgeType.DERIVED_FROM,
    )
    graph.add_edge(edge)
    graph.validate_final_claim_traceability()
    with pytest.raises(ValueError, match="already exists"):
        graph.add_edge(edge)
    with pytest.raises(ValidationError, match="unique"):
        ClaimGraphSnapshot(nodes=(graph.snapshot().nodes[0],) * 2, edges=())
    with pytest.raises(ValidationError, match="unknown endpoint"):
        ClaimGraphSnapshot(
            nodes=graph.snapshot().nodes,
            edges=(
                GraphEdge(
                    edge_id="edge_unknown",
                    source_id="claim_node",
                    target_id="claim_unknown",
                    edge_type=EdgeType.CONTRADICTS,
                ),
            ),
        )


def test_claim_graph_cycles_are_prohibited() -> None:
    graph = ClaimGraph()
    graph.add_node(_evidence_node("evidence_cycle"))
    graph.add_node(
        GraphNode(node_id="claim_cycle_a", node_type=NodeType.CLAIM, substantive_final_claim=True)
    )
    graph.add_node(GraphNode(node_id="claim_cycle_b", node_type=NodeType.CLAIM))
    graph.add_edge(
        GraphEdge(
            edge_id="edge_cycle_evidence",
            source_id="evidence_cycle",
            target_id="claim_cycle_b",
            edge_type=EdgeType.SUPPORTS,
        )
    )
    graph.add_edge(
        GraphEdge(
            edge_id="edge_cycle_ab",
            source_id="claim_cycle_a",
            target_id="claim_cycle_b",
            edge_type=EdgeType.DERIVED_FROM,
        )
    )
    with pytest.raises(ValueError, match="cycles"):
        graph.add_edge(
            GraphEdge(
                edge_id="edge_cycle_ba",
                source_id="claim_cycle_b",
                target_id="claim_cycle_a",
                edge_type=EdgeType.DERIVED_FROM,
            )
        )


def test_graph_snapshot_order_is_canonical() -> None:
    nodes = (
        GraphNode(node_id="claim_zed", node_type=NodeType.CLAIM),
        GraphNode(node_id="claim_alpha", node_type=NodeType.CLAIM),
    )
    left = ClaimGraphSnapshot(nodes=nodes, edges=())
    right = ClaimGraphSnapshot(nodes=tuple(reversed(nodes)), edges=())
    assert left == right


def test_graph_identity_relationship_and_inventory_are_bound_to_ledger() -> None:
    result = run_demo("provisional")
    snapshot = result.claim_graph.snapshot()
    result.claim_graph.validate_against_ledger(result.evidence_ledger)
    evidence_node = next(node for node in snapshot.nodes if node.node_type is NodeType.EVIDENCE)
    changed_node = evidence_node.model_copy(update={"evidence_sha256": "f" * 64})
    identity_graph = ClaimGraph.from_snapshot(
        ClaimGraphSnapshot(
            nodes=tuple(
                changed_node if node.node_id == changed_node.node_id else node
                for node in snapshot.nodes
            ),
            edges=snapshot.edges,
        )
    )
    with pytest.raises(ValueError, match="identity"):
        identity_graph.validate_against_ledger(result.evidence_ledger)
    edge = snapshot.edges[0]
    changed_edge = edge.model_copy(update={"edge_type": EdgeType.QUALIFIES})
    relationship_graph = ClaimGraph.from_snapshot(
        ClaimGraphSnapshot(nodes=snapshot.nodes, edges=(changed_edge,))
    )
    with pytest.raises(ValueError, match="relationship"):
        relationship_graph.validate_against_ledger(result.evidence_ledger)
    inventory_graph = ClaimGraph()
    inventory_graph.add_node(
        GraphNode(
            node_id=result.case.claim.claim_id,
            node_type=NodeType.CLAIM,
            substantive_final_claim=True,
        )
    )
    with pytest.raises(ValueError, match="inventory"):
        inventory_graph.validate_against_ledger(result.evidence_ledger)
