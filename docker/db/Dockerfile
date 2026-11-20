# PostGIS for the mart's geometry, pgvector for the document index.
#
# Neither upstream image ships both: `postgis/postgis` has no vector type and
# `pgvector/pgvector` has no PostGIS. The pgvector base is used because it
# already carries the PGDG apt repository, so the PostGIS package resolves
# there; the reverse is not true.
FROM pgvector/pgvector:pg16

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-16-postgis-3 \
        postgresql-16-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*
