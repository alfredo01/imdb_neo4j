#!/usr/bin/env bash
#
# Rebuild the three neo4j-admin import files from the IMDB dumps.
#
#   title.basics.tsv     -> movies.csv        (all title nodes, :LABEL from titleType)
#   name.basics.tsv      -> people_names.csv  (Person nodes)
#   title.principals.tsv -> roles.csv         (all relationships, :TYPE from category)
#
# Localised titles are folded into movies.csv as extra columns rather than
# loaded separately: neo4j-admin takes properties as columns, so the join
# happens here once instead of as 24M index lookups against a live database.
#
# Both inputs of that join are sorted by title id (IMDB ships them that way, and
# the filter preserved it), so it runs as a merge join in constant memory.
#
# Usage: ./build_import_csv.sh [source_dir] [output_dir]

set -euo pipefail

SRC="${1:-.}"
OUT="${2:-./import_csv}"
mkdir -p "$OUT"

export LC_ALL=C

echo "==> 1/4  aggregating regional titles, one row per title"
# akas_filtered.tsv is titleId, title, region, isOriginalTitle — several rows per
# title. Collapse consecutive rows of the same title into one wide row. First
# occurrence per region wins; IMDB orders them by descending relevance.
awk -F'\t' -v OFS='\t' '
  NR == 1 { next }
  $1 != cur {
    if (cur != "") print cur, fr, es, pt, it
    cur = $1; fr = es = pt = it = ""
  }
  $3 == "FR" && fr == "" { fr = $2 }
  $3 == "ES" && es == "" { es = $2 }
  $3 == "PT" && pt == "" { pt = $2 }
  $3 == "IT" && it == "" { it = $2 }
  END { if (cur != "") print cur, fr, es, pt, it }
' "$SRC/akas_filtered.tsv" > "$OUT/akas_wide.tsv"

echo "==> 2/4  movies.csv"
awk -F'\t' -v OFS='\t' -v AKAS="$OUT/akas_wide.tsv" '
  function advance(   line) {
    if ((getline line < AKAS) > 0) { split(line, A, "\t"); akid = A[1] }
    else akid = "\xff\xff"           # sentinel: sorts after every real tconst
  }
  function clean(v) { return (v == "\\N") ? "" : v }

  BEGIN {
    label["movie"]        = "Movie";        label["short"]       = "Short"
    label["tvEpisode"]    = "Tvepisode";    label["tvSeries"]    = "Tvseries"
    label["tvMovie"]      = "Tvmovie";      label["tvMiniSeries"] = "Tvminiseries"
    label["tvSpecial"]    = "Tvspecial";    label["tvShort"]     = "Tvshort"
    label["video"]        = "Video";        label["videoGame"]   = "Videogame"
    label["tvPilot"]      = "Tvpilot"
    advance()
    print "movieId:ID", "title", "originalTitle", "year",
          "title_fr", "title_es", "title_pt", "title_it", ":LABEL"
  }

  NR == 1 { next }
  !($2 in label) { next }              # unknown titleType: no label to give it

  {
    while (akid < $1) advance()
    if (akid == $1) {
      print $1, clean($3), clean($4), clean($6), A[2], A[3], A[4], A[5], label[$2]
      advance()
    } else {
      print $1, clean($3), clean($4), clean($6), "", "", "", "", label[$2]
    }
  }
' "$SRC/title.basics.tsv" > "$OUT/movies.csv"

echo "==> 3/4  people_names.csv"
awk -F'\t' -v OFS='\t' '
  function clean(v) { return (v == "\\N") ? "" : v }
  NR == 1 { print "personId:ID", "name", "birthYear", "deathYear"; next }
  { print $1, clean($2), clean($3), clean($4) }
' "$SRC/name.basics.tsv" > "$OUT/people_names.csv"

echo "==> 4/4  roles.csv"
# category is IMDB's own vocabulary and maps one-to-one onto the relationship
# types already in the graph; actor and actress both collapse to ACTED_IN.
# `characters` arrives as a JSON array — the brackets and quotes are stripped so
# the value lands as plain text, and tabs cannot appear inside it.
awk -F'\t' -v OFS='\t' '
  BEGIN {
    t["actor"] = "ACTED_IN";              t["actress"] = "ACTED_IN"
    t["director"] = "DIRECTED";           t["writer"] = "WROTE"
    t["producer"] = "PRODUCED";           t["composer"] = "COMPOSED"
    t["editor"] = "EDITED";               t["cinematographer"] = "CINEMATOGRAPHER"
    t["production_designer"] = "PRODUCTION_DESIGNER"
    t["casting_director"] = "CASTING_EDITOR"
    t["self"] = "SELF"
    t["archive_footage"] = "ARCHIVE_FOOTAGE"
    t["archive_sound"] = "ARCHIVE_SOUND"
    print ":START_ID", ":END_ID", ":TYPE", "role"
  }
  NR == 1 { next }
  !($4 in t) { next }
  {
    role = $6
    if (role == "\\N") role = ""
    else { gsub(/[\[\]"]/, "", role) }
    print $3, $1, t[$4], role
  }
' "$SRC/title.principals.tsv" > "$OUT/roles.csv"

rm -f "$OUT/akas_wide.tsv"

echo
echo "==> done"
wc -l "$OUT"/*.csv
du -h "$OUT"/*.csv
