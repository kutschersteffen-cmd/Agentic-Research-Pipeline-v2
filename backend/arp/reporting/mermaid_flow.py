"""Parse a Mermaid flowchart subset into a typed `Flow` (spec house-deck-flowchart-slides, "Mermaid subset")."""

from __future__ import annotations

from arp.schemas.mermaid_parser import OTHER_DIAGRAMS, RESERVED, MermaidError, parse_mermaid_dict  # noqa: F401
from arp.schemas.visuals import Flow


def parse_mermaid(text: str) -> Flow:
    """Parse Mermaid flowchart text into a `Flow` (layout none); raise `MermaidError` on anything outside the subset."""
    return Flow.model_validate(parse_mermaid_dict(text)).model_copy(update={"mermaid": text})
