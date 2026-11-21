# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
class ConfigError(Exception):
    pass


class RootRefused(Exception):
    """Startup refused because the effective uid is 0."""


class ApiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class PersistError(Exception):
    pass


class EnumeratorError(Exception):
    pass
