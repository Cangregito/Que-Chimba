import os
import sys
import unittest
from unittest.mock import patch


CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
	sys.path.insert(0, CURRENT_DIR)

import bot


class ConfirmationFlowRegressionTest(unittest.TestCase):
	def test_pulido_ia_omite_mensajes_operativos(self):
		base = "Listo mi llave. Como prefiere recibir su pedido?"

		with patch.object(bot, "LLM_STYLE_ENABLED", True), patch.object(bot, "requests", object()), patch.object(bot, "_post_ollama_generate", side_effect=AssertionError("No deberia invocar IA en mensajes operativos")):
			resultado = bot._pulir_texto_con_ia(base, {"tipo_servicio": "individual"})

		self.assertEqual(resultado, base)

	def test_resumen_pedido_prefiere_items_reales(self):
		datos_temp = {
			"items": [
				{
					"producto_id": 1,
					"nombre": "Empanada",
					"variante": "carne",
					"cantidad": 3,
					"precio_unit": 35,
				},
				{
					"producto_id": 5,
					"nombre": "Jugo",
					"variante": "300ml natural",
					"cantidad": 1,
					"precio_unit": 25,
				},
			],
			"total": 130,
			"tipo_servicio": "individual",
			"metodo_entrega": "recoger_tienda",
			"metodo_pago": "efectivo",
			"producto_nombre": "Empanada carne",
			"cantidad": 2,
			"precio_unitario": 35,
		}

		with patch.object(bot, "_obtener_catalogo_productos", return_value=[]):
			resumen = bot._resumen_pedido(datos_temp)

		self.assertIn("- 3x Empanada carne $105.00", resumen)
		self.assertIn("- 1x Jugo 300ml natural $25.00", resumen)
		self.assertIn("TOTAL: $130 MXN", resumen)
		self.assertNotIn("Cantidad: 2", resumen)

	def test_handle_completado_normaliza_items_legacy_antes_de_guardar(self):
		sesion = {
			"datos_temp": {
				"producto_id": 1,
				"producto_nombre": "Empanada carne",
				"cantidad": 2,
				"precio_unitario": 35,
				"metodo_entrega": "recoger_tienda",
				"metodo_pago": "efectivo",
				"requiere_factura": False,
				"cliente_nombre": "Yahir Medina",
			}
		}
		cliente = {"cliente_id": 77, "whatsapp_id": "5210000000000", "nombre": "Yahir Medina"}

		with patch.object(bot, "_persistir_datos_cliente"), patch.object(bot.db, "crear_pedido_completo", return_value={"pedido_id": 123, "codigo_entrega": "ABC123"}) as crear_mock:
			out = bot.handle_completado(sesion, "confirmar", cliente)

		self.assertEqual(out["nuevo_estado"], "completado")
		self.assertEqual(out["datos_temp"]["pedido_id"], 123)
		self.assertEqual(out["datos_temp"]["codigo_entrega"], "ABC123")
		kwargs = crear_mock.call_args.kwargs
		self.assertEqual(kwargs["cliente_id"], 77)
		self.assertEqual(kwargs["datos_temp"]["items"][0]["producto_id"], 1)
		self.assertEqual(kwargs["datos_temp"]["items"][0]["cantidad"], 2)


if __name__ == "__main__":
	unittest.main()