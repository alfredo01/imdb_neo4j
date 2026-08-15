"""Localised movie titles for the frontend's display-label fallback.

`title` is IMDB's English primary title, `title_fr` and friends are the regional
release titles loaded from title.akas, and `originalTitle` is the film in its own
language. Coverage of the regional ones is thin — around 12% of Movie nodes have
a French title — so the frontend falls back title_<lang> -> original -> title,
and this carries only what actually exists rather than padding the payload with
nulls.
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
