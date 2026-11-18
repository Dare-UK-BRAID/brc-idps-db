import io
import unittest

from scripts.query_idps import write_wide_tsv


class WriteTsvTests(unittest.TestCase):
    def test_writes_wide_rows_and_empty_fields_for_nulls(self):
        output = io.StringIO()
        count = write_wide_tsv(
            output,
            ["IDP_A", "IDP_B"],
            [
                ("subject-1", "IDP_A", 1.25),
                ("subject-1", "IDP_B", None),
                ("subject-2", "IDP_A", None),
                ("subject-2", "IDP_B", -3.0),
            ],
        )
        self.assertEqual(count, 2)
        self.assertEqual(
            output.getvalue(),
            "SubjectID\tIDP_A\tIDP_B\n"
            "subject-1\t1.25\t\n"
            "subject-2\t\t-3.0\n",
        )

    def test_writes_header_for_no_matches(self):
        output = io.StringIO()
        count = write_wide_tsv(output, ["IDP_A"], [])
        self.assertEqual(count, 0)
        self.assertEqual(output.getvalue(), "SubjectID\tIDP_A\n")

    def test_rejects_duplicate_values_for_subject_and_idp(self):
        with self.assertRaisesRegex(ValueError, "Multiple values"):
            write_wide_tsv(
                io.StringIO(),
                ["IDP_A"],
                [("subject-1", "IDP_A", 1.0), ("subject-1", "IDP_A", 2.0)],
            )


if __name__ == "__main__":
    unittest.main()
