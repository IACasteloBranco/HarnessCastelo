import unittest

from governanca.server.data_protection import Action, Category, Finding, detect, inspect


class DataProtectionTests(unittest.TestCase):
    def policy(self, **changes):
        return {category: Action(changes.get(category.value, "mask")) for category in Category}

    def inspect(self, text, **changes):
        return inspect(text, self.policy(**changes), policy_version="synthetic-1")

    def test_document_formats_and_checksums(self):
        for value, category in (
            ("123.456.789-09", Category.CPF), ("12345678909", Category.CPF),
            ("12.ABC.345/01DE-35", Category.CNPJ), ("12ABC34501DE35", Category.CNPJ),
            ("12.abc.345/01de-35", Category.CNPJ),
            ("11.222.333/0001-81", Category.CNPJ), ("11222333000181", Category.CNPJ),
        ):
            with self.subTest(value=value):
                self.assertIn(category, [item.category for item in detect(value)])
                self.assertEqual(self.inspect(value).text, f"[{category.value}_1]")

    def test_rejects_invalid_documents_and_embedded_identifiers(self):
        for value in ("111.111.111-11", "00000000000000", "123.456.789-00",
                      "12.ABC.345/01DE-36", "x12345678909x", "112223330001810"):
            with self.subTest(value=value):
                self.assertFalse(any(item.category in (Category.CPF, Category.CNPJ) for item in detect(value)))

    def test_preserves_text_and_original_character_positions(self):
        text = "Olá 😀! CPF 123.456.789-09; email teste@example.invalid.\nFim"
        result = self.inspect(text)
        self.assertEqual(result.text, "Olá 😀! CPF [CPF_1]; email [EMAIL_1].\nFim")
        self.assertEqual([text[item.start:item.end] for item in result.findings],
                         ["123.456.789-09", "teste@example.invalid"])

    def test_multiple_occurrences_and_marker_collisions(self):
        result = self.inspect("[CPF_1] 123.456.789-09 e 12345678909")
        self.assertEqual(result.text, "[CPF_1] [CPF_2] e [CPF_3]")

    def test_phone_formats_and_invalid_ddd(self):
        for value in ("+55 (11) 91234-5678", "(21) 2345-6789", "11912345678", "11 91234 5678"):
            with self.subTest(value=value):
                self.assertEqual(self.inspect(value).text, "[PHONE_1]")
        for value in ("(20) 91234-5678", "1234-5678", "(11) 61234-5678", "999999999999999"):
            with self.subTest(value=value):
                self.assertFalse(any(item.category == Category.PHONE for item in detect(value)))

    def test_overlap_returns_all_findings_but_masks_whole_email(self):
        text = "12345678909@example.invalid e 11912345678@example.invalid"
        result = self.inspect(text)
        self.assertIn(Category.CPF, [item.category for item in result.findings])
        self.assertIn(Category.PHONE, [item.category for item in result.findings])
        self.assertEqual(result.text, "[EMAIL_1] e [EMAIL_2]")

    def test_policy_is_separate_and_block_has_precedence_even_inside_email(self):
        text = "12345678909@example.invalid"
        self.assertEqual(self.inspect(text, CPF="block").action, Action.BLOCK)
        self.assertIsNone(self.inspect(text, CPF="block").text)
        result = self.inspect("12.ABC.345/01DE-35", CNPJ="allow")
        self.assertEqual(result.action, Action.ALLOW)
        self.assertEqual(result.text, "12.ABC.345/01DE-35")
        self.assertTrue(result.findings)

    def test_clean_text_and_explicit_policy_validation(self):
        self.assertEqual(self.inspect("sem dados").text, "sem dados")
        self.assertEqual(self.inspect("").action, Action.ALLOW)
        with self.assertRaises(ValueError):
            inspect("", {}, policy_version="1")
        with self.assertRaises(ValueError):
            inspect("", self.policy(), policy_version=" ")
        with self.assertRaises(ValueError):
            inspect("", dict.fromkeys(Category, "mask"), policy_version="1")
        with self.assertRaises(ValueError):
            inspect("abc", self.policy(), policy_version="1",
                    additional_findings=(Finding(Category.EMAIL, 0, 4),))


if __name__ == "__main__":
    unittest.main()
