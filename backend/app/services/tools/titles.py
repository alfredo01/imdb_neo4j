"""Localised movie titles for the frontend's display-label fallback.

`title` is IMDB's English primary title, `title_fr` and friends are the regional
release titles loaded from title.akas, and `originalTitle` is the film in its own
language. Coverage of the regional ones is thin. Counted 2026-08-19 across
all 748,081 Movie nodes: fr 94,150 (12.6%), it 76,427 (10.2%), es 74,114
(9.9%), pt 43,965 (5.9%); a further 95,344 (12.7%) carry an `originalTitle`
that differs from `title`. So the frontend falls back
title_<lang> -> original -> title, and this carries only what actually exists
rather than padding the payload with nulls.

Re-measure with a full `count()`, never a `LIMIT` sample: scan order tracks
tconst, and the prominent titles at the front are far better covered than the
tail. The first 50k Movies put French at 34.6%, nearly three times the real
figure.
"""

LANGUAGES = ("fr", "es", "pt", "it")


def localised_titles(props):
    """The alternative titles of a movie, keyed by language, empties dropped.

    `original` is only worth sending when it differs from the label the node
    already carries; for an English-language film the two are the same string.
    """
    titles = {lang: props[f"title_{lang}"]
              for lang in LANGUAGES if props.get(f"title_{lang}")}
    original = props.get("originalTitle")
    if original and original != props.get("title"):
        titles["original"] = original
    return titles
