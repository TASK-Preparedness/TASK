# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Reserved extension point for a future secure emergency bridge (mesh <-> APRS <-> GMRS <-> LAN).

NOT IMPLEMENTED and not approved. Phase 4C has no relay of any kind: txpolicy refuses every
request whose origin is not the local UI. A future bridge would need its own approval, the full
platform policy engine (spec 11 §6), and for GMRS §95.1733(a)(8)/(9) make most bridging unlawful.
"""


class Bridge:
    """Interface only. Every method refuses."""

    name = "none"

    def forward(self, *_args, **_kwargs):
        raise PermissionError("relaying between networks is not available in T.A.S.K. 0.3.0")
