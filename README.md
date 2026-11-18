# BRC IDP PostgreSQL tools

This project builds two containers that use the same PostgreSQL table,
`"postgresSchema"."BRC_IDPS"`, with `subjid`, `idp`, and nullable `value`
columns.

## Loader container

The loader imports a wide-format TSV with a `SubjectID` column and one column
per IDP. Each subject/IDP pair is stored as one database row. Empty values and
`NaN` values are stored as SQL `NULL`.

The target table is created if needed. If it already contains rows, the loader
stops unless `--overwrite` is supplied. With `--overwrite`, existing rows are
deleted only for subject IDs present in the TSV, then replaced by that TSV's
values in a single transaction. Rows for other subjects are preserved.
After insertion, the loader runs a `SELECT` to verify the inserted row count
and non-NULL value count, and logs both counts. A mismatch fails the load and
rolls back the transaction.

Generate the Dockerfile only:

```bash
python3 build.py --no-build
```

Build and load the loader image into the local Docker engine:

```bash
python3 build.py
```

Optionally push `martincraig/brc-idps-db:latest` after building:

```bash
python3 build.py --push
```

To run the loader, provide the six PostgreSQL settings in a protected env file
and mount the TSV:

```bash
mkdir -p outputs
docker run --rm \
    --env-file postgres.env \
    -v "$PWD/IDPs.tsv:/input/IDPs.tsv:ro" \
    -v "$PWD/outputs:/output" \
    martincraig/brc-idps-db \
    /input/IDPs.tsv --overwrite
```

`postgres.env` must define `postgresServer`, `postgresPort`,
`postgresDatabase`, `postgresSchema`, `postgresUsername`, and
`postgresPassword`. Keep this file private.

## Query/export container

Build and optionally push the query image:

```bash
python3 build.py --product query
python3 build.py --product query --push
```

The query container exports a wide TSV with `SubjectID` followed by one column
per IDP, ordered by subject and IDP name. Empty database values are output as
empty TSV fields. The output path must be writable inside the container (usually
by mounting an output directory):

```bash
mkdir -p outputs
docker run --rm \
    --env-file postgres.env \
    -v "$PWD/outputs:/output" \
    martincraig/brc-idps-db-query \
    -o /output/IDPs.tsv
```

Subject and IDP filters are optional and can be repeated:

```bash
docker run --rm \
    --env-file postgres.env \
    -v "$PWD/outputs:/output" \
    martincraig/brc-idps-db-query \
    -o /output/selected.tsv \
    --subject 005_S_10101 \
    --subject 005_S_10102 \
    --idp dMRI_TBSS_ODI_45
```
