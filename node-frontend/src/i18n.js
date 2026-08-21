// UI copy in the visitor's language.
//
// Deliberately the same five languages the title data covers: fr/es/pt/it are
// the regions loaded from title.akas (see build_import_csv.sh), and English is
// both IMDB's primary-title language and everyone else's fallback. Adding a
// language here without a matching title_<lang> column would wrap localised
// chrome around English titles, which reads worse than staying in English.

import { preferredLanguages } from "./titles";

const STRINGS = {
  en: {
    graphHint:
      "Click a node for its Wikipedia summary · double-click it to explore its connections",
    exampleQuery:
      "Show the graph of Alfred Hitchcock movies, with actors between 1950 and 1960",
  },
  fr: {
    graphHint:
      "Cliquez sur un nœud pour afficher son résumé Wikipédia · double-cliquez pour explorer ses connexions",
    exampleQuery:
      "Affiche le graphe des films d'Alfred Hitchcock, avec les acteurs entre 1950 et 1960",
  },
  es: {
    graphHint:
      "Haz clic en un nodo para ver su resumen de Wikipedia · haz doble clic para explorar sus conexiones",
    exampleQuery:
      "Muestra el grafo de las películas de Alfred Hitchcock, con los actores entre 1950 y 1960",
  },
  pt: {
    graphHint:
      "Clique num nó para ver o resumo da Wikipédia · clique duas vezes para explorar as conexões",
    exampleQuery:
      "Mostra o grafo dos filmes de Alfred Hitchcock, com os atores entre 1950 e 1960",
  },
  it: {
    graphHint:
      "Clicca su un nodo per vedere il riassunto di Wikipedia · fai doppio clic per esplorare le sue connessioni",
    exampleQuery:
      "Mostra il grafo dei film di Alfred Hitchcock, con gli attori tra il 1950 e il 1960",
  },
};

// The first of the reader's languages we have copy for. Reusing
// preferredLanguages() is what keeps chrome and titles agreeing: a reader who
// sees "L'armée des ombres" on the nodes gets the French hint above them, and
// one who falls through to English titles gets the English hint.
let resolved = null;

export function uiLanguage() {
  if (resolved) return resolved;
  for (const lang of preferredLanguages()) {
    if (STRINGS[lang]) return (resolved = lang);
  }
  return (resolved = "en");
}

// English is the fallback for a key missing from a translation, so a partially
// translated language degrades to mixed copy rather than to `undefined`.
export function t(key) {
  const lang = uiLanguage();
  return STRINGS[lang]?.[key] ?? STRINGS.en[key];
}
