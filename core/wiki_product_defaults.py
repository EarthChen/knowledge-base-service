"""Product-specific wiki defaults — not applied unless copied into deployment config.

Set via env, e.g. ``WIKI__TERM_OVERRIDES`` (JSON) or dashboard system settings.
"""

from __future__ import annotations

# HelloGroup / 挚友 — English slug fragments → canonical Chinese product terms.
HELLOGROUP_TERM_OVERRIDES: dict[str, str] = {
    "closed-friend": "挚友",
    "closed friend": "挚友",
}
