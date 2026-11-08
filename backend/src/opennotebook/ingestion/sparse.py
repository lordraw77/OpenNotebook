"""BM25-style sparse vectors computed algorithmically (no model).

Documents get saturated term frequencies (BM25 TF component); Qdrant applies the IDF part through the sparse
vector `idf` modifier. Terms are hashed to 32-bit indices, so no vocabulary has to be stored.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter

K1 = 1.2
B = 0.75
AVG_DOC_LEN = 256

_TOKEN = re.compile(r"\w+", re.UNICODE)

STOPWORDS = frozenset(
    # English
    "a an and are as at be but by for from has have he her his how i if in into is it its of on or our "
    "she so than that the their them then there these they this to was we were what when where which "
    "while who why will with you your "
    # Italian
    "a ad al alla alle agli ai anche che chi ci col come con da dal dalla dalle dei del della delle dello di "
    "e ed gli ha hanno il in io la le lei lo loro lui ma mi ne negli nei nel nella nelle no noi non o per "
    "perché più quale quando quello questa questo se si sia sono su sua sue suo sui sul sulla tra tu un una "
    "uno vi voi".split()
)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    return [t for t in _TOKEN.findall(text) if len(t) > 1 and t not in STOPWORDS]


def term_index(term: str) -> int:
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big")


def _vector(weights: dict[int, float]) -> tuple[list[int], list[float]]:
    items = sorted(weights.items())
    return [i for i, _ in items], [round(v, 6) for _, v in items]


def document_vector(text: str) -> tuple[list[int], list[float]]:
    tokens = tokenize(text)
    if not tokens:
        return [], []
    length = len(tokens)
    norm = K1 * (1 - B + B * length / AVG_DOC_LEN)
    weights: dict[int, float] = {}
    for term, tf in Counter(tokens).items():
        idx = term_index(term)
        weights[idx] = weights.get(idx, 0.0) + tf * (K1 + 1) / (tf + norm)
    return _vector(weights)


def query_vector(text: str) -> tuple[list[int], list[float]]:
    return _vector({term_index(t): 1.0 for t in set(tokenize(text))})
