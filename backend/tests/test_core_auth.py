"""Pure core auth primitives (`arp.core.auth`) and backward-compatible re-exports from `arp.api.auth`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arp.api import auth as api_auth
from arp.core import auth as core_auth


def test_core_auth_primitives_and_api_reexports():
    assert api_auth.Principal is core_auth.Principal
    assert api_auth.ROLE_RANK is core_auth.ROLE_RANK
    assert api_auth.GRANTS is core_auth.GRANTS
    assert core_auth.ROLE_RANK == {"viewer": 0, "analyst": 1, "approver": 2}
    assert set(core_auth.GRANTS) == {"snapshot_reader", "holdings_reader"}

    p = core_auth.Principal(user_id="u1", name="Alice", role="analyst", roles=["holdings_reader"])
    assert p.role == "analyst" and p.roles == ["holdings_reader"]

    with pytest.raises(ValidationError):
        core_auth.Principal(user_id="u2", name="Bob", role="analyst", roles=["unknown_grant"])
