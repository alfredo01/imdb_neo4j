// Node labels arrive as IMDB's primary title, which is English. When the backend
// also carried a regional title for one of the reader's languages, that is the
// better thing to show; the film's own language is the next best; IMDB's title is
// the floor. People nodes have no `titles`, so they fall through untouched.

// The reader's languages, most preferred first, reduced to the base subtag a
// Wikipedia edition is named after ("fr-CA" -> "fr"). English is appended as the
// universal fallback: it is the largest edition, so when the reader's own
// language has no article it is the one most likely to.
export function preferredLanguages() {
  const raw = (typeof navigator !== "undefined" && (navigator.languages || [navigator.language])) || [];
  const codes = raw.filter(Boolean).map(l => l.toLowerCase().split("-")[0]);
  return [...new Set([...codes, "en"])].slice(0, 3);
}

// The title to show for a node. `en` never matches a key in `titles` — the
// English title is already `label` — so an English reader lands on the floor,
// which is what they want.
export function displayLabel(node) {
  if (!node) return "";
  const titles = node.titles;
  if (!titles) return node.label;
  for (const lang of preferredLanguages()) {
    if (titles[lang]) return titles[lang];
  }
  return titles.original || node.label;
}

// The title to search Wikipedia with, in a given language edition. A regional
// title is far likelier to be the article name there than IMDB's English one:
// the fr.wikipedia article is "L'armée des ombres", never "Army of Shadows".
export function titleInLanguage(node, lang) {
  return node?.titles?.[lang] || node?.label;
}
