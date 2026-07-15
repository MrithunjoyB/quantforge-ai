"""Minimal typed research claim graph with evidence traceability checks."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from quantforge.domain.models import Identifier, StrictModel


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
        known = set(node_ids)
        if any(edge.source_id not in known or edge.target_id not in known for edge in self.edges):
            raise ValueError("claim graph edge has an unknown endpoint")
        return self


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
        self._edges[edge.edge_id] = edge

    def validate_final_claim_traceability(self) -> None:
        evidence_ids = {
            node.node_id for node in self._nodes.values() if node.node_type is NodeType.EVIDENCE
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

    @classmethod
    def from_snapshot(cls, snapshot: ClaimGraphSnapshot) -> ClaimGraph:
        graph = cls()
        for node in snapshot.nodes:
            graph.add_node(node)
        for edge in snapshot.edges:
            graph.add_edge(edge)
        return graph
