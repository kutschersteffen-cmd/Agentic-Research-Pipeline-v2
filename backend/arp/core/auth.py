"""Pure authentication identity primitives shared across domains and entrypoints."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

ROLE_RANK: dict[str, int] = {"viewer": 0, "analyst": 1, "approver": 2}
Grant = Literal["snapshot_reader", "holdings_reader"]
GRANTS: tuple[str, ...] = get_args(Grant)


class Principal(BaseModel):
    user_id: str
    name: str
    role: Literal["viewer", "analyst", "approver"]
    roles: list[Grant] = Field(default_factory=list)  # grants beyond the role rank; a typo fails at load
