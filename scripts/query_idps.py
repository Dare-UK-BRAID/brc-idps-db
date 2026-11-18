#!/usr/bin/env python3
"""Export IDPs from PostgreSQL as a wide-format TSV."""

import argparse
import csv
import logging
import os
import sys
import tempfile
from pathlib import Path


LOG = logging.getLogger("query_idps")
BATCH_SIZE = 1000


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


def write_wide_tsv(output, idp_names, records):
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["SubjectID", *idp_names])
    idp_indexes = {name: index for index, name in enumerate(idp_names)}
    current_subject = None
    values = None
    seen_idps = set()
    count = 0

    def write_subject(subject_id, idp_values):
        nonlocal count
        writer.writerow([subject_id, *idp_values])
        count += 1

    for subject_id, idp_name, value in records:
        if subject_id != current_subject:
            if current_subject is not None:
                write_subject(current_subject, values)
            current_subject = subject_id
            values = [None] * len(idp_names)
            seen_idps = set()

        if idp_name not in idp_indexes:
            raise ValueError(f"Unexpected IDP returned by query: {idp_name!r}")
        if idp_name in seen_idps:
            raise ValueError(
                f"Multiple values found for subject {subject_id!r}, IDP {idp_name!r}"
            )
        values[idp_indexes[idp_name]] = value
        seen_idps.add(idp_name)

    if current_subject is not None:
        write_subject(current_subject, values)
    return count


def export_tsv(output_path, subjects=None, idps=None):
    import psycopg
    from psycopg import sql

    config = required_environment()
    table = sql.Identifier(config["postgresSchema"], "BRC_IDPS")

    with psycopg.connect(
        host=config["postgresServer"],
        port=config["postgresPort"],
        dbname=config["postgresDatabase"],
        user=config["postgresUsername"],
        password=config["postgresPassword"],
    ) as connection:
        with connection.cursor() as cursor:
            idp_query = sql.SQL("SELECT DISTINCT idp FROM {}").format(table)
            idp_parameters = ()
            if idps:
                idp_names = list(dict.fromkeys(idps))
            else:
                idp_query += sql.SQL(" ORDER BY idp")
                cursor.execute(idp_query)
                idp_names = [row[0] for row in cursor.fetchall()]

            if any(not name or len(name) > 100 for name in idp_names):
                raise ValueError("IDP names in the table must be non-empty and at most 100 characters")
            if "SubjectID" in idp_names:
                raise ValueError("An IDP named 'SubjectID' conflicts with the output subject column")

        query = sql.SQL("SELECT subjid, idp, value FROM {}").format(table)
        parameters = []
        conditions = []
        if idps:
            conditions.append(sql.SQL("idp = ANY(%s)"))
            parameters.append(idps)
        if subjects:
            conditions.append(sql.SQL("subjid = ANY(%s)"))
            parameters.append(subjects)
        if conditions:
            query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        query += sql.SQL(" ORDER BY subjid, idp")

        output_path = Path(output_path)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                with connection.cursor(name="brc_idps_export") as cursor:
                    cursor.execute(query, parameters)

                    def records():
                        while batch := cursor.fetchmany(BATCH_SIZE):
                            yield from batch

                    count = write_wide_tsv(output, idp_names, records())
            os.replace(temporary_path, output_path)
            return count
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def main():
    logging.basicConfig(
        level=os.environ.get("IDPS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        help="Output TSV file path",
    )
    parser.add_argument(
        "--subject",
        action="append",
        dest="subjects",
        help="Subject ID to include; repeat to select multiple subjects",
    )
    parser.add_argument(
        "--idp",
        action="append",
        dest="idps",
        help="IDP name to include; repeat to select multiple IDPs",
    )
    args = parser.parse_args()

    try:
        import psycopg
    except ImportError as exc:
        LOG.error("PostgreSQL driver is unavailable: %s", exc)
        return 1

    try:
        count = export_tsv(args.output, subjects=args.subjects, idps=args.idps)
    except psycopg.Error as exc:
        LOG.error("PostgreSQL query failed: %s", exc)
        return 1
    except (OSError, ValueError) as exc:
        LOG.error("%s", exc)
        return 1

    LOG.info("Exported %d subject(s) to %s", count, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
