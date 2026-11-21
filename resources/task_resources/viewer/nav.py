# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Back/forward navigation (shared by both viewers)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    rid: int
    path: str
    fragment: str = ""


class Navigator:
    def __init__(self, limit=200):
        self.back_stack, self.forward_stack, self.current, self.limit = [], [], None, limit

    def go(self, loc: Location):
        if self.current is not None and loc != self.current:
            self.back_stack.append(self.current)
            del self.back_stack[:-self.limit]
            self.forward_stack.clear()
        self.current = loc

    def replace(self, loc: Location):
        self.current = loc

    def can_back(self):
        return bool(self.back_stack)

    def can_forward(self):
        return bool(self.forward_stack)

    def back(self):
        if not self.back_stack:
            return None
        self.forward_stack.append(self.current)
        self.current = self.back_stack.pop()
        return self.current

    def forward(self):
        if not self.forward_stack:
            return None
        self.back_stack.append(self.current)
        self.current = self.forward_stack.pop()
        return self.current
