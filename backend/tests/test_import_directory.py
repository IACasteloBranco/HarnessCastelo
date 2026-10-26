import unittest

from backend.scripts.import_directory import _validate_rows


class DirectoryImportTests(unittest.TestCase):
    def test_validates_codes_and_department_assignments(self):
        header = {"A": "Departamentos", "B": "Código", "D": "Funcionário",
                  "E": "Código", "F": "Departamento"}
        rows = [header, {"A": "Fiscal", "B": "dept-01", "D": "Ana Silva",
                         "E": "COLAB-001", "F": "Fiscal"}]
        self.assertEqual(_validate_rows(rows),
                         ([("Fiscal", "dept-01")], [("Ana Silva", "COLAB-001", "Fiscal")]))

        with self.assertRaisesRegex(ValueError, "duplicate employee code"):
            _validate_rows(rows + [{"D": "Outra Pessoa", "E": "COLAB-001", "F": "Fiscal"}])
        with self.assertRaisesRegex(ValueError, "unknown departments"):
            _validate_rows(rows + [{"D": "Outra Pessoa", "E": "COLAB-002", "F": "Outro"}])


if __name__ == "__main__":
    unittest.main()
