import tempfile
import unittest
from pathlib import Path

from scripts.load_idps import (
    delete_subject_rows,
    iter_idp_records,
    verify_insert_counts,
)


class IterIdpRecordsTests(unittest.TestCase):
    def read_records(self, text):
        temporary_file = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False
        )
        try:
            temporary_file.write(text)
            temporary_file.close()
            return list(iter_idp_records(temporary_file.name))
        finally:
            Path(temporary_file.name).unlink(missing_ok=True)

    def test_wide_tsv_becomes_long_records_and_empty_values_are_null(self):
        records = self.read_records(
            "SubjectID\tIDP_A\tIDP_B\nsubject-1\t1.25\t\nsubject-2\tNaN\t-3\n"
        )
        self.assertEqual(
            records,
            [
                ("subject-1", "IDP_A", 1.25),
                ("subject-1", "IDP_B", None),
                ("subject-2", "IDP_A", None),
                ("subject-2", "IDP_B", -3.0),
            ],
        )

    def test_rejects_missing_subject_column_and_malformed_rows(self):
        with self.assertRaisesRegex(ValueError, "subject column"):
            self.read_records("IDP_A\n1\n")
        with self.assertRaisesRegex(ValueError, "expected 2"):
            self.read_records("SubjectID\tIDP_A\nsubject-1\n")

    def test_rejects_non_numeric_idp_value(self):
        with self.assertRaisesRegex(ValueError, "not a number"):
            self.read_records("SubjectID\tIDP_A\nsubject-1\tbad\n")


class VerifyInsertCountsTests(unittest.TestCase):
    class Cursor:
        def __init__(self, counts):
            self.counts = counts
            self.executed_query = None

        def execute(self, query, parameters=None):
            self.executed_query = (query, parameters)

        def fetchone(self):
            return self.counts

    def test_select_counts_must_match_inserted_row_and_value_counts(self):
        cursor = self.Cursor((12, 9))
        verify_insert_counts(cursor, "verify query", ["subject-1"], 12, 9)
        self.assertEqual(cursor.executed_query, ("verify query", (["subject-1"],)))

    def test_mismatch_fails_verification(self):
        with self.assertRaisesRegex(RuntimeError, "found 12 row"):
            verify_insert_counts(
                self.Cursor((12, 8)), "verify query", ["subject-1"], 12, 9
            )

    def test_overwrite_deletes_only_rows_for_imported_subjects(self):
        cursor = self.Cursor(None)
        delete_subject_rows(cursor, "delete query", ["subject-1", "subject-2"])
        self.assertEqual(
            cursor.executed_query,
            ("delete query", (["subject-1", "subject-2"],)),
        )

    def test_empty_import_does_not_delete_any_rows(self):
        cursor = self.Cursor(None)
        delete_subject_rows(cursor, "delete query", [])
        self.assertIsNone(cursor.executed_query)


if __name__ == "__main__":
    unittest.main()
