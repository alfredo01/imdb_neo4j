#!/usr/bin/env bash
#
# Rebuild the Neo4j store on the VPS from the generated import CSVs.
#
# Run from the directory holding docker-compose.yaml, with the three CSVs
# already in ./neo4j/raw_data (mounted into the container as its import dir).
#
# This DESTROYS the existing store. Everything computed lives in it —
# centrality, embedding, embeddingSage — and none of it survives. The app is
# down from step 2 until compute_centrality.py finishes.
#
# Usage: NEO4J_PASSWORD=... ./vps_import.sh

set -euo pipefail

IMPORT_DIR=/var/lib/neo4j/import
: "${NEO4J_PASSWORD:?set NEO4J_PASSWORD}"

for f in movies.csv people_names.csv roles.csv; do
  [ -f "./neo4j/raw_data/$f" ] || { echo "missing ./neo4j/raw_data/$f"; exit 1; }
done

echo "==> 1/5  stopping services"
docker compose stop fastapi neo4j

echo "==> 2/5  backing up the current store"
# Cheap insurance: the import is not reversible, and a failed run leaves no
# database at all. Rename rather than copy — a rename on the same filesystem
# costs nothing, where copying 25M nodes would cost tens of gigabytes.
#
# The transaction logs live in a sibling directory and must move with the store.
# Leaving them behind pairs a fresh store with the old store's logs, and Neo4j
# refuses to open that — a confusing failure well after the import has finished.
STAMP="$(date +%Y%m%d-%H%M%S)"
for dir in databases transactions; do
  if [ -d "./neo4j/data/$dir/neo4j" ]; then
    mv "./neo4j/data/$dir/neo4j" "./neo4j/data/$dir/neo4j.bak.$STAMP"
  fi
done

echo "==> 3/5  importing (this is the long one)"
docker compose run --rm neo4j neo4j-admin database import full \
  --overwrite-destination \
  --delimiter='\t' \
  --skip-bad-relationships \
  --skip-duplicate-nodes \
  --nodes="$IMPORT_DIR/movies.csv" \
  --nodes=Person="$IMPORT_DIR/people_names.csv" \
  --relationships="$IMPORT_DIR/roles.csv" \
  neo4j

echo "==> 4/5  starting neo4j"
docker compose up -d neo4j
until docker compose exec -T neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
        "RETURN 1" >/dev/null 2>&1; do
  echo "    waiting for bolt ..."
  sleep 5
done

echo "==> 5/5  recreating indexes and constraints"
# The import creates none of these. entity_mapper.py cannot resolve a name typed
# into the chat box without the two full-text indexes, so the app looks broken
# in a way that has nothing to do with the data.
docker compose exec -T neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" <<'CYPHER'
CREATE CONSTRAINT person_id_unique IF NOT EXISTS FOR (p:Person) REQUIRE p.personId IS UNIQUE;
CREATE CONSTRAINT movie_id_unique  IF NOT EXISTS FOR (m:Movie)  REQUIRE m.movieId  IS UNIQUE;
CREATE INDEX person_name_idx IF NOT EXISTS FOR (p:Person) ON (p.name);
CREATE INDEX movie_title_idx IF NOT EXISTS FOR (m:Movie)  ON (m.title);
CREATE FULLTEXT INDEX personNameIndex IF NOT EXISTS FOR (n:Person) ON EACH [n.name];
CREATE FULLTEXT INDEX movieTitleIndex IF NOT EXISTS FOR (n:Movie)
  ON EACH [n.title, n.originalTitle, n.title_fr, n.title_es, n.title_pt, n.title_it];
CYPHER

echo
echo "==> import done. Still required before the app is usable:"
echo "      docker compose exec fastapi python -m app.services.compute_centrality"
echo "      docker compose exec fastapi python -m app.services.compute_embeddings"
echo "    then: docker compose up -d fastapi"
