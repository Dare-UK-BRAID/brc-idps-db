#!/usr/bin/env python3
"""Load a wide-format IDP TSV into PostgreSQL as subject/IDP/value rows."""

import argparse
import csv
import logging
import math
import os
import sys
from pathlib import Path


LOG = logging.getLogger("load_idps")
SUBJECT_COLUMN = "SubjectID"
BATCH_SIZE = 1000
NULL_VALUES = {"", "na", "nan", "null", "none"}


def iter_idp_records(path, subject_column=SUBJECT_COLUMN):
    """Yield (subject ID, IDP name, nullable float) records from a TSV file."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as tsv_file:
        reader = csv.reader(tsv_file, delimiter="\t")
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ValueError("The TSV file is empty") from exc

        if len(headers) != len(set(headers)):
            raise ValueError("The TSV header contains duplicate column names")
        if subject_column not in headers:
            raise ValueError(
                f"Required subject column {subject_column!r} is missing from the TSV"
            )

        subject_index = headers.index(subject_column)
        idp_columns = [(index, name) for index, name in enumerate(headers) if index != subject_index]
        if not idp_columns:
            raise ValueError("The TSV must contain at least one IDP column")
        invalid_idp_names = [name for _, name in idp_columns if not name or len(name) > 100]
        if invalid_idp_names:
            raise ValueError("IDP column names must be non-empty and at most 100 characters")

        for line_number, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(headers):
                raise ValueError(
                    f"Line {line_number} has {len(row)} columns; expected {len(headers)}"
                )

            subject_id = row[subject_index].strip()
            if not subject_id:
                raise ValueError(f"Line {line_number} has an empty {subject_column} value")
            if len(subject_id) > 200:
                raise ValueError(f"Line {line_number} has a subject ID longer than 200 characters")

            for index, idp_name in idp_columns:
                raw_value = row[index].strip()
                if raw_value.lower() in NULL_VALUES:
                    value = None
                else:
                    try:
                        value = float(raw_value)
                    except ValueError as exc:
                        raise ValueError(
                            f"Line {line_number}, IDP {idp_name!r}: "
                            f"{raw_value!r} is not a number"
                        ) from exc
                    if math.isnan(value):
                        value = None
                yield subject_id, idp_name, value


def required_environment():
    names = (
        "postgresServer",
        "postgresPort",
        "postgresDatabase",
        "postgresSchema",
        "postgresUsername",
        "postgresPassword",
    )
    values = {name: os.environ.get(name) for name in names}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        raise ValueError("Missing environment variable(s): " + ", ".join(missing))

    try:
        values["postgresPort"] = int(values["postgresPort"])
    except ValueError as exc:
        raise ValueError("postgresPort must be an integer") from exc
    if not 1 <= values["postgresPort"] <= 65535:
        raise ValueError("postgresPort must be between 1 and 65535")
    return values


def verify_insert_counts(cursor, query, subject_ids, expected_rows, expected_non_null):
    cursor.execute(query, (subject_ids,))
    verified_rows, verified_non_null = cursor.fetchone()
    if (verified_rows, verified_non_null) != (expected_rows, expected_non_null):
        raise RuntimeError(
            "Post-insert verification failed: expected "
            f"{expected_rows} row(s) and {expected_non_null} non-NULL value(s), "
            f"found {verified_rows} row(s) and {verified_non_null} "
            "non-NULL value(s)"
        )


def delete_subject_rows(cursor, query, subject_ids):
    if subject_ids:
        cursor.execute(query, (subject_ids,))


def load_tsv(path, overwrite=False):
    import psycopg
    from psycopg import sql

    config = required_environment()
    table = sql.Identifier(config["postgresSchema"], "BRC_IDPS")
    create_table = sql.SQL(
        "CREATE TABLE IF NOT EXISTS {} "
        "(subjid VARCHAR(200) NOT NULL, idp VARCHAR(100) NOT NULL, value FLOAT NULL)"
    ).format(table)
    check_rows = sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(table)
    delete_rows = sql.SQL("DELETE FROM {} WHERE subjid = ANY(%s)").format(table)
    insert_rows = sql.SQL(
        "INSERT INTO {} (subjid, idp, value) VALUES (%s, %s, %s)"
    ).format(table)
    verify_rows = sql.SQL(
        "SELECT COUNT(*), COUNT(value) FROM {} WHERE subjid = ANY(%s)"
    ).format(table)

    inserted = 0
    non_null_inserted = 0
    with psycopg.connect(
        host=config["postgresServer"],
        port=config["postgresPort"],
        dbname=config["postgresDatabase"],
        user=config["postgresUsername"],
        password=config["postgresPassword"],
    ) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(create_table)
                cursor.execute(sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(table))
                cursor.execute(check_rows)
                has_rows = cursor.fetchone()[0]
                if has_rows and not overwrite:
                    raise ValueError(
                        "The target table already contains rows; pass --overwrite "
                        "to replace rows for subjects in the TSV"
                    )

                subject_ids = list(
                    dict.fromkeys(
                        subject_id
                        for subject_id, _, _ in iter_idp_records(path)
                    )
                )
                if overwrite:
                    delete_subject_rows(cursor, delete_rows, subject_ids)

                batch = []
                for record in iter_idp_records(path):
                    batch.append(record)
                    if len(batch) == BATCH_SIZE:
                        cursor.executemany(insert_rows, batch)
                        inserted += len(batch)
                        non_null_inserted += sum(value is not None for _, _, value in batch)
                        batch.clear()
                if batch:
                    cursor.executemany(insert_rows, batch)
                    inserted += len(batch)
                    non_null_inserted += sum(value is not None for _, _, value in batch)

                verify_insert_counts(
                    cursor,
                    verify_rows,
                    subject_ids,
                    inserted,
                    non_null_inserted,
                )
    return inserted, non_null_inserted


def main():
    logging.basicConfig(
        level=os.environ.get("IDPS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv", type=Path, help="Wide-format IDP TSV input file")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing rows only for subjects present in this TSV",
    )
    args = parser.parse_args()

    if not args.tsv.is_file():
        parser.error(f"TSV file does not exist or is not a file: {args.tsv}")

    try:
        import psycopg
    except ImportError as exc:
        LOG.error("PostgreSQL driver is unavailable: %s", exc)
        return 1

    try:
        inserted, non_null_inserted = load_tsv(args.tsv, overwrite=args.overwrite)
    except psycopg.Error as exc:
        LOG.error("PostgreSQL load failed: %s", exc)
        return 1
    except (OSError, ValueError) as exc:
        LOG.error("%s", exc)
        return 1
    except RuntimeError as exc:
        LOG.error("%s", exc)
        return 1

    LOG.info(
        "Post-insert verification passed: %d IDP row(s), %d non-NULL value(s) "
        "in the database (loaded from %s)",
        inserted,
        non_null_inserted,
        args.tsv,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
