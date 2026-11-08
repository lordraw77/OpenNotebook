"""Citation markers `[S3]` in model answers: parsing, validation and coverage checks.

The model only ever writes `[Sn]` markers that refer to the numbered passages it was given; page numbers and
titles are added by the client from stored metadata, so the model cannot invent them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# [S1]  [S1, S3]  [S1; S2]  [s2]  — also tolerates "Source 1" written inside brackets.
_GROUP = re.compile(r"(\s*)\[((?:\s*(?:S|Source\s*)\d+\s*[,;]?)+)\]", re.IGNORECASE)
_NUMBER = re.compile(r"\d+")
# a sentence ends at . ! ? followed by whitespace (so "4.2.1", "v1.2" and "file.py" do not split it)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_INLINE_CODE = re.compile(r"`[^`]*`")
_ABBREVIATIONS = re.compile(r"\b(e\.g|i\.e|etc|vs|cf|p|pp|ca|approx|es|ecc)\.", re.IGNORECASE)
# "...the device. [S1]" — a marker right after the full stop belongs to the sentence before it
_TRAILING_MARKERS = re.compile(r"([.!?])((?:\s*\[S\d+\])+)")

NOT_FOUND = "I could not find this information in the selected sources."
# Phrases that signal an abstention, also in Italian (answers follow the language of the question).
_ABSTAIN = re.compile(
    r"could not find this information|non (?:ho trovato|sono riuscit[oa] a trovare|trovo) "
    r"(?:questa informazione|questa informazione nelle fonti|informazioni)",
    re.IGNORECASE,
)


@dataclass
class CitationCheck:
    content: str
    cited: list[int] = field(default_factory=list)  # valid passage numbers, in order of first use
    invalid: list[str] = field(default_factory=list)
    uncited_sentences: int = 0
    abstained: bool = False


def normalize(content: str, available: int) -> CitationCheck:
    """Rewrite every marker group as `[S1][S3]`, dropping numbers outside 1..available."""
    check = CitationCheck(content="")

    def repl(match: re.Match[str]) -> str:
        out = []
        for raw in _NUMBER.findall(match.group(2)):
            n = int(raw)
            if 1 <= n <= available:
                if n not in check.cited:
                    check.cited.append(n)
                out.append(f"[S{n}]")
            else:
                check.invalid.append(f"S{n}")
        # a group with only invalid numbers disappears together with the space before it
        return match.group(1) + "".join(dict.fromkeys(out)) if out else ""

    check.content = _GROUP.sub(repl, content)
    check.abstained = bool(_ABSTAIN.search(content))
    check.uncited_sentences = 0 if check.abstained else count_uncited(check.content)
    return check


def count_uncited(content: str) -> int:
    """Factual-looking sentences without a marker (headings, list labels and code are ignored)."""
    count = 0
    in_code = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped or stripped.startswith("#"):
            continue
        stripped = _TRAILING_MARKERS.sub(r"\2\1", stripped)
        stripped = _ABBREVIATIONS.sub(lambda m: m.group(1), _INLINE_CODE.sub("code", stripped))
        for sentence in _SENTENCE_SPLIT.split(stripped):
            sentence = sentence.strip()
            if sentence.endswith(":"):  # lead-in to a list, not a claim
                continue
            words = sentence.strip(" -*>").split()
            if len(words) >= 6 and "[S" not in sentence:
                count += 1
    return count


def strip_markers(content: str) -> str:
    """Remove markers, e.g. from history turns (passage numbers change with every question)."""
    return re.sub(r"\s*\[S\d+\]", "", content)
