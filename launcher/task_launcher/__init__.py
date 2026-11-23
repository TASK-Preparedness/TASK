# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-launcher: the native T.A.S.K. (T.A.S.K.) launcher and app platform (Phase 3, extended in Phase 4A).

T.A.S.K. remains the technical name; the shown title is configurable (branding.py).
The launcher never touches hardware: everything device-related goes through task-core.
"""

__version__ = "0.3.8"
# Version of the launcher platform that app manifests compare ``min_platform`` against.
PLATFORM_VERSION = "0.2.0"
