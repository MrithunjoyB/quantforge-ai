from __future__ import annotations

import pytest
from pydantic import ValidationError

from quantforge.evidence.graph import (
    ClaimGraph,
    ClaimGraphSnapshot,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
)


def test_claim_graph_traceability_and_roundtrip() -> None:
    graph = ClaimGraph()
    graph.add_node(GraphNode(node_id="evidence_source", node_type=NodeType.EVIDENCE))
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


def test_claim_graph_rejects_duplicate_edge_and_corrupt_snapshots() -> None:
    graph = ClaimGraph()
    graph.add_node(GraphNode(node_id="claim_node", node_type=NodeType.CLAIM))
    edge = GraphEdge(
        edge_id="edge_self",
        source_id="claim_node",
        target_id="claim_node",
        edge_type=EdgeType.AMENDS,
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


def test_claim_graph_cycle_is_bounded_and_traceable() -> None:
    graph = ClaimGraph()
    graph.add_node(GraphNode(node_id="evidence_cycle", node_type=NodeType.EVIDENCE))
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
    graph.add_edge(
        GraphEdge(
            edge_id="edge_cycle_ba",
            source_id="claim_cycle_b",
            target_id="claim_cycle_a",
            edge_type=EdgeType.DERIVED_FROM,
        )
    )
    graph.validate_final_claim_traceability()
