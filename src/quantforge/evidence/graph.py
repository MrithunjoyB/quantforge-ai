"""Minimal typed research claim graph with evidence traceability checks."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from quantforge.domain.models import Identifier, Sha256, StrictModel, ValidationStatus
from quantforge.evidence.ledger import EvidenceLedger


class NodeType(StrEnum):
    CLAIM = "claim"
    EVIDENCE = "evidence"
    AMENDMENT = "amendment"


class EdgeType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    DERIVED_FROM = "derived_from"
    AMENDS = "amends"


class GraphNode(StrictModel):
    node_id: Identifier
    node_type: NodeType
    substantive_final_claim: bool = False
    evidence_sha256: Sha256 | None = None
    evidence_validation_status: ValidationStatus | None = None

    @model_validator(mode="after")
    def type_specific_fields(self) -> Self:
        evidence_fields = (self.evidence_sha256, self.evidence_validation_status)
        if self.node_type is NodeType.EVIDENCE and (
            self.evidence_sha256 is None or self.evidence_validation_status is None
        ):
            raise ValueError("evidence graph nodes require content and validation identity")
        if self.node_type is not NodeType.EVIDENCE and any(
            value is not None for value in evidence_fields
        ):
            raise ValueError("only evidence graph nodes may carry evidence identity")
        if self.node_type is not NodeType.CLAIM and self.substantive_final_claim:
            raise ValueError("only claim nodes may be substantive final claims")
        return self


class GraphEdge(StrictModel):
    edge_id: Identifier
    source_id: Identifier
    target_id: Identifier
    edge_type: EdgeType


class ClaimGraphSnapshot(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @model_validator(mode="after")
    def valid_graph(self) -> Self:
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("claim graph identifiers must be unique")
        edge_meanings = [(edge.source_id, edge.target_id, edge.edge_type) for edge in self.edges]
        if len(edge_meanings) != len(set(edge_meanings)):
            raise ValueError("claim graph contains a duplicate semantic edge")
        known = set(node_ids)
        if any(edge.source_id not in known or edge.target_id not in known for edge in self.edges):
            raise ValueError("claim graph edge has an unknown endpoint")
        nodes_by_id = {node.node_id: node for node in self.nodes}
        _validate_edge_types(nodes_by_id, self.edges)
        _assert_acyclic(known, self.edges)
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda node: node.node_id)))
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=lambda edge: edge.edge_id)))
        return self


def _validate_edge_types(
    nodes: dict[str, GraphNode], edges: tuple[GraphEdge, ...] | list[GraphEdge]
) -> None:
    for edge in edges:
        source = nodes[edge.source_id].node_type
        target = nodes[edge.target_id].node_type
        valid = (
            (
                edge.edge_type in {EdgeType.SUPPORTS, EdgeType.CONTRADICTS, EdgeType.QUALIFIES}
                and source is NodeType.EVIDENCE
                and target is NodeType.CLAIM
            )
            or (
                edge.edge_type is EdgeType.DERIVED_FROM
                and source is NodeType.CLAIM
                and target is NodeType.CLAIM
            )
            or (
                edge.edge_type is EdgeType.AMENDS
                and source is NodeType.AMENDMENT
                and target in {NodeType.AMENDMENT, NodeType.CLAIM}
            )
        )
        if not valid or edge.source_id == edge.target_id:
            raise ValueError("claim graph edge violates the node-type contract")


def _assert_acyclic(node_ids: set[str], edges: tuple[GraphEdge, ...] | list[GraphEdge]) -> None:
    successors: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        if edge.target_id not in successors[edge.source_id]:
            successors[edge.source_id].add(edge.target_id)
            indegree[edge.target_id] += 1
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for successor in sorted(successors[node_id]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
    if visited != len(node_ids):
        raise ValueError("claim graph cycles are prohibited")


class ClaimGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}

    def add_node(self, node: GraphNode) -> None:
        if node.node_id in self._nodes:
            raise ValueError("claim graph node already exists")
        self._nodes[node.node_id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.edge_id in self._edges:
            raise ValueError("claim graph edge already exists")
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            raise ValueError("claim graph edge endpoint does not exist")
        prospective = [*self._edges.values(), edge]
        if any(
            (item.source_id, item.target_id, item.edge_type)
            == (edge.source_id, edge.target_id, edge.edge_type)
            for item in self._edges.values()
        ):
            raise ValueError("claim graph semantic edge already exists")
        _validate_edge_types(self._nodes, prospective)
        _assert_acyclic(set(self._nodes), prospective)
        self._edges[edge.edge_id] = edge

    def validate_final_claim_traceability(self) -> None:
        evidence_ids = {
            node.node_id
            for node in self._nodes.values()
            if node.node_type is NodeType.EVIDENCE
            and node.evidence_validation_status is ValidationStatus.VALIDATED
        }
        reverse: dict[str, set[str]] = {}
        for edge in self._edges.values():
            if edge.edge_type in {
                EdgeType.SUPPORTS,
                EdgeType.CONTRADICTS,
                EdgeType.QUALIFIES,
            }:
                reverse.setdefault(edge.target_id, set()).add(edge.source_id)
            elif edge.edge_type is EdgeType.DERIVED_FROM:
                reverse.setdefault(edge.source_id, set()).add(edge.target_id)
        for node in self._nodes.values():
            if node.node_type is not NodeType.CLAIM or not node.substantive_final_claim:
                continue
            frontier = [node.node_id]
            visited: set[str] = set()
            found = False
            while frontier:
                current = frontier.pop()
                if current in visited:
                    continue
                visited.add(current)
                for predecessor in reverse.get(current, set()):
                    if predecessor in evidence_ids:
                        found = True
                    frontier.append(predecessor)
            if not found:
                raise ValueError(f"final claim lacks evidence traceability: {node.node_id}")

    def snapshot(self) -> ClaimGraphSnapshot:
        return ClaimGraphSnapshot(
            nodes=tuple(self._nodes.values()),
            edges=tuple(self._edges.values()),
        )

    def validate_against_ledger(self, ledger: EvidenceLedger) -> None:
        snapshot = ledger.snapshot()
        evidence_by_id = {item.evidence_id: item for item in snapshot.evidence}
        graph_evidence_ids = {
            node.node_id for node in self._nodes.values() if node.node_type is NodeType.EVIDENCE
        }
        if graph_evidence_ids != set(evidence_by_id):
            raise ValueError("claim graph evidence inventory does not match the ledger")
        for node_id in graph_evidence_ids:
            node = self._nodes[node_id]
            evidence = evidence_by_id[node_id]
            if (
                node.evidence_sha256 != evidence.content_sha256
                or node.evidence_validation_status is not evidence.validation_status
            ):
                raise ValueError("claim graph evidence identity does not match the ledger")
        for edge in self._edges.values():
            if edge.source_id in evidence_by_id:
                relationship = evidence_by_id[edge.source_id].relationship.value
                if edge.edge_type.value != relationship:
                    raise ValueError("claim graph relationship does not match evidence")

    @classmethod
    def from_snapshot(cls, snapshot: ClaimGraphSnapshot) -> ClaimGraph:
        graph = cls()
        for node in snapshot.nodes:
            graph.add_node(node)
        for edge in snapshot.edges:
            graph.add_edge(edge)
        return graph
