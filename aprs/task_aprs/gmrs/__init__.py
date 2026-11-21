# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""GMRS data profile: separate config, attestation, audit stream and TX controls from amateur APRS.

Only the certified GMRS hand-held's own built-in data function may transmit (47 CFR §95.1731(d), §95.1787,
§95.339). T.A.S.K. never generates GMRS modulation itself: a driver asks the RADIO to send its own packet."""
