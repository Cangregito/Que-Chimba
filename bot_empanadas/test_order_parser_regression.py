import os
import sys
import unittest
from unittest.mock import patch


CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
	sys.path.insert(0, CURRENT_DIR)

import bot


CATALOGO_FAKE = [
	{
		"producto_id": 1,
		"nombre": "Empanada",
		"variante": "carne",
		"precio": 35,
	},
	{
		"producto_id": 2,
		"nombre": "Empanada",
		"variante": "pollo",
		"precio": 35,
	},
	{
		"producto_id": 3,
		"nombre": "Agua",
		"variante": "500ml botella",
		"precio": 15,
	},
	{
		"producto_id": 4,
		"nombre": "Refresco",
		"variante": "cola",
		"precio": 20,
	},
	{
		"producto_id": 5,
		"nombre": "Jugo",
		"variante": "naranja",
		"precio": 25,
	},
]


class OrderParserRegressionTest(unittest.TestCase):
	def parse(self, texto):
		with patch.object(bot, "_obtener_catalogo_productos", return_value=CATALOGO_FAKE), patch.object(bot.db, "buscar_regla_curada_parser", return_value=None):
			return bot._extraer_items_menu_oficial(texto)

	def quantities(self, resultado):
		return {int(item["producto_id"]): int(item["cantidad"]) for item in resultado.get("items") or []}

	def test_natural_single_order(self):
		resultado = self.parse("Una empanada de carne y un agua")
		self.assertEqual(self.quantities(resultado), {1: 1, 3: 1})
		self.assertFalse(resultado.get("needs_clarification"))
		self.assertFalse(resultado.get("needs_confirmation"))
		self.assertGreaterEqual(float(resultado.get("confidence_score") or 0), 0.95)
		self.assertEqual(resultado.get("parse_mode"), "explicit")

	def test_numeric_plural_order(self):
		resultado = self.parse("2 de pollo y 3 aguas")
		self.assertEqual(self.quantities(resultado), {2: 2, 3: 3})

	def test_mixed_number_words(self):
		resultado = self.parse("dos empanadas de carne y una de pollo")
		self.assertEqual(self.quantities(resultado), {1: 2, 2: 1})

	def test_beverages_order(self):
		resultado = self.parse("1 refresco y un jugo")
		self.assertEqual(self.quantities(resultado), {4: 1, 5: 1})

	def test_fallback_assumptions_require_confirmation(self):
		resultado = self.parse("agua y carne")
		self.assertEqual(self.quantities(resultado), {1: 1, 3: 1})
		self.assertTrue(resultado.get("needs_confirmation"))
		self.assertLess(float(resultado.get("confidence_score") or 0), 0.9)
		self.assertEqual(resultado.get("parse_mode"), "inferred")

	def test_generic_empanada_requires_clarification(self):
		resultado = self.parse("una empanada y un agua")
		self.assertTrue(resultado.get("needs_clarification"))
		self.assertIn("carne", (resultado.get("clarification_message") or "").lower())
		self.assertIn("pollo", (resultado.get("clarification_message") or "").lower())
		self.assertEqual(self.quantities(resultado), {3: 1})
		self.assertLess(float(resultado.get("confidence_score") or 0), 0.3)
		self.assertEqual(resultado.get("parse_mode"), "clarification_required")

	def test_split_de_cada(self):
		resultado = self.parse("6 de cada carne y pollo")
		self.assertEqual(self.quantities(resultado), {1: 3, 2: 3})

	def test_docena_word(self):
		resultado = self.parse("docena de carne")
		self.assertEqual(self.quantities(resultado), {1: 12})

	def test_media_docena_word(self):
		resultado = self.parse("media docena de pollo")
		self.assertEqual(self.quantities(resultado), {2: 6})

	def test_no_double_count_for_water(self):
		resultado = self.parse("1 agua")
		self.assertEqual(self.quantities(resultado), {3: 1})

	def test_curated_rule_exact_match(self):
		regla = {
			"regla_id": 99,
			"frase_original": "lo de siempre",
			"items_json": [{"producto_id": 1, "cantidad": 2}, {"producto_id": 3, "cantidad": 1}],
			"needs_confirmation": False,
			"needs_clarification": False,
			"clarification_message": "",
		}
		with patch.object(bot, "_obtener_catalogo_productos", return_value=CATALOGO_FAKE), patch.object(bot.db, "buscar_regla_curada_parser", return_value=regla):
			resultado = bot._extraer_items_menu_oficial("lo de siempre")
		self.assertEqual(self.quantities(resultado), {1: 2, 3: 1})
		self.assertEqual(resultado.get("parse_mode"), "curated_rule")
		self.assertEqual(int(resultado.get("matched_rule_id") or 0), 99)


if __name__ == "__main__":
	unittest.main()