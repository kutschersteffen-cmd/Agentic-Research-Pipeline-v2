"""Vertical-slice bounded contexts for the ARP modular monolith.

Cross-domain calls must go through `arp.domains.<domain>.public` (enforced by
`.github/scripts/arch_guard.py --strict`).
"""

from __future__ import annotations

DOMAINS = ("stewardiq", "argus", "transition", "rd_lab", "data_hub")
