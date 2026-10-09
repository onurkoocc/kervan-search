"""Tokenizing shared by the simulated embeddings and snippet selection."""

import re

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """
    a an and are as at be been but by can do does for from has have how i if in
    into is it its may me my no not of on or our so than that the their them then
    there they this to was we what when where which who will with you your
    """.split()
)


def stem(word: str) -> str:
    """A deliberately small suffix stripper: 'deliveries' -> 'delivery', 'rescheduling' -> 'reschedul'."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("ing") and len(word) > 5:
        word = word[:-3]
    elif word.endswith("ed") and len(word) > 4:
        word = word[:-2]
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]
