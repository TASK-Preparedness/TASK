# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Topic classification of INDEXED resources by metadata rules (Phase 4F.3). Read-only, no I/O.

A resource is "medical" when the user put it in a category named Medical, or when its indexed metadata (title,
name, description, publisher, creator, file name, categories) matches a named collection or a medical keyword
rule. Every match reports the rule that fired, so the UI can show *why* an item is listed. Nothing is
inferred beyond the indexed metadata; nothing is fetched.
"""

import re
from pathlib import Path

MEDICAL_CATEGORY = "Medical"

# (label, regex) — named collections first (most specific). Patterns are matched case-insensitively against
# the joined metadata with "_", "-" and "." turned into spaces.
MEDICAL_COLLECTIONS = (
    ("MDWiki", r"\bmdwiki\b|\bwikiproject med\b|\bwikimed\b"),
    ("WikEM", r"\bwikem\b"),
    ("MedlinePlus", r"\bmedline ?plus\b"),
    ("Medicine LibreTexts", r"\blibretexts\b.*\bmed(icine|ical)?\b|\bmed(icine)? libretexts\b"),
    ("Military Medicine", r"\bmilitary medicine\b|\bfas military medicine\b|\btactical combat casualty\b"),
    ("Medical Library", r"\bmedical library\b"),
    ("Hesperian Health Guides", r"\bhesperian\b"),
    ("Where There Is No Doctor", r"\bwhere there is no doctor\b"),
)
MEDICAL_KEYWORDS = (
    ("keyword: medicine/medical", r"\bmedic(al|ine|ines)\b"),
    ("keyword: first aid", r"\bfirst aid\b"),
    ("keyword: health", r"\b(public )?health(care)?\b"),
    ("keyword: anatomy", r"\banatom(y|ical)\b"),
    ("keyword: pharmacology", r"\bpharmac(y|ology|eutical)s?\b"),
    ("keyword: nursing", r"\bnurs(e|es|ing)\b"),
    ("keyword: emergency care", r"\b(emergency|trauma) (medicine|care)\b|\bparamedic\b|\bems\b"),
    ("keyword: clinical", r"\bclinical\b|\bsurgery\b|\bsurgical\b|\bdisease(s)?\b|\bdentist(ry)?\b|\bdental\b"),
)
_COMPILED = [(lbl, re.compile(rx, re.I)) for lbl, rx in MEDICAL_COLLECTIONS + MEDICAL_KEYWORDS]


def _text(r):
    parts = [r.get("title"), r.get("name"), r.get("description"), r.get("publisher"), r.get("creator"),
             Path(r.get("path") or "").stem, " ".join(r.get("categories") or [])]
    return re.sub(r"[_\-.]+", " ", " ".join(p for p in parts if p))


def medical_reason(r):
    """-> '' when not medical, else the rule that matched ('category: Medical', 'MDWiki', 'keyword: …')."""
    if any(c.casefold() == MEDICAL_CATEGORY.casefold() for c in (r.get("categories") or [])):
        return f"category: {MEDICAL_CATEGORY}"
    t = _text(r)
    for lbl, rx in _COMPILED:
        if rx.search(t):
            return lbl
    return ""


def is_medical(r):
    return bool(medical_reason(r))
