# Mission

## What this project is
A **visual graph exploration platform** for knowledge graphs. The user enters
a natural-language question; the system translates it into a graph query,
fetches a relevant subgraph, and renders it as an interactive **timeline
bubble chart** and a **force-directed graph**.

The goal is to let non-technical users explore a domain through its
relationships — who collaborated with whom, when, and how strongly — without
writing a single line of Cypher or SPARQL.

## First domain: cinema (IMDB)
The current dataset is IMDB, modeled in Neo4j with three node types
(`Person` covering directors and actors, `Movie`) and the relationships
between them (`ACTED_IN`, `DIRECTED`, etc.). Cinema is the proving ground
for the visual idiom and the agent pipeline.

## Next domain: music (WIKIDATA via SPARQL)
The same idiom — timeline bubbles + force graph — will be applied to music:
artists, bands, albums, and the collaborations between them. Music data will
not be re-ingested into Neo4j; instead a SPARQL adapter will query WIKIDATA
(and similar endpoints) directly, so the platform can extend to new domains
without an ingestion pipeline per source.

## Beyond visualization: recommendation and clustering
Once the graph and the agent pipeline are stable across two domains, the
platform extends to **content-oriented recommendations** based on shared
collaborators (artist↔artist, actor↔actor, director↔actor) and to
**cluster detection** — surfacing communities of frequent collaborators as a
first-class exploration primitive.

## Non-goals
- Building a general-purpose chatbot. The agent exists to drive the
  visualization, not to answer arbitrary questions.
- Replacing IMDb, Wikipedia, or Spotify as a data source. The platform is a
  lens over existing knowledge graphs.
- Owning long-term storage for non-cinema data. WIKIDATA stays in WIKIDATA.

## Success looks like
- A user types "show me Christopher Nolan's collaborators in the 2000s" and
  gets a readable timeline + force graph in seconds.
- The same surface, with a different adapter, answers "show me the bands
  Thom Yorke played with" against WIKIDATA.
- Recommendations and clusters appear as additional layers on the same
  visualization, not as a separate product.