import os
import sys
import unittest
from unittest.mock import patch


CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
	sys.path.insert(0, CURRENT_DIR)

import bot


class ConfirmationFlowRegressionTest(unittest.TestCase):
	def test_enriquecimiento_no_pisa_slots_legacy_con_carrito_en_confirmacion(self):
		datos_temp = {
			"items": [
				{"producto_id": 1, "nombre": "Empanada", "variante": "carne", "cantidad": 2, "precio_unit": 35},
				{"producto_id": 2, "nombre": "Empanada", "variante": "pollo", "cantidad": 2, "precio_unit": 35},
			],
			"total": 140,
			"metodo_entrega": "domicilio",
			"metodo_pago": "efectivo",
		}

		with patch.object(bot, "_obtener_catalogo_productos", return_value=[]):
			resultado = bot._enriquecer_datos_desde_entrada(
				"confirmo 4 de carne",
				datos_temp,
				usar_llm=False,
				estado_actual="confirmacion",
			)

		self.assertEqual(resultado.get("items"), datos_temp["items"])
		self.assertEqual(resultado.get("total"), 140)
		self.assertIsNone(resultado.get("cantidad"))
		self.assertIsNone(resultado.get("producto_id"))

	def test_enriquecimiento_llm_no_pisa_slots_legacy_con_carrito_en_confirmacion(self):
		datos_temp = {
			"items": [
				{"producto_id": 1, "nombre": "Empanada", "variante": "carne", "cantidad": 2, "precio_unit": 35},
				{"producto_id": 2, "nombre": "Empanada", "variante": "pollo", "cantidad": 2, "precio_unit": 35},
			],
			"total": 140,
			"metodo_entrega": "domicilio",
			"metodo_pago": "efectivo",
		}

		slots_llm = {
			"producto": "carne",
			"cantidad": 4,
			"confirmar": True,
		}

		with patch.object(bot, "_extraer_slots_llm", return_value=slots_llm), patch.object(bot, "_normalizar_slots_llm", side_effect=lambda x: x), patch.object(bot, "_obtener_catalogo_productos", return_value=[]):
			resultado = bot._enriquecer_datos_desde_entrada(
				"confirmo 4 de carne",
				datos_temp,
				usar_llm=True,
				estado_actual="confirmacion",
			)

		self.assertEqual(resultado.get("items"), datos_temp["items"])
		self.assertEqual(resultado.get("total"), 140)
		self.assertIsNone(resultado.get("cantidad"))
		self.assertIsNone(resultado.get("producto_id"))

	def test_pulido_ia_omite_mensajes_operativos(self):
		base = "Listo mi llave. Como prefiere recibir su pedido?"

		with patch.object(bot, "LLM_STYLE_ENABLED", True), patch.object(bot, "requests", object()), patch.object(bot, "_post_ollama_generate", side_effect=AssertionError("No deberia invocar IA en mensajes operativos")):
			resultado = bot._pulir_texto_con_ia(base, {"tipo_servicio": "individual"})

		self.assertEqual(resultado, base)

	def test_respuesta_con_opciones_no_invoca_pulido_ia(self):
		with patch.object(bot, "_pulir_texto_con_ia", side_effect=AssertionError("No deberia pulir respuestas con opciones")):
			respuesta = bot._armar_respuesta_comercial(
				"Ey Michelle, bienvenido a La Malparida Empanada. Elija una opcion para arrancar.",
				"1) Quiero pedir empanadas\n2) Es para evento\n3) Ver menu y precios",
				{},
			)

		self.assertIn("1) Quiero pedir empanadas", respuesta["contenido"])
		self.assertIn("2) Es para evento", respuesta["contenido"])

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

	def test_metodo_entrega_acepta_opciones_numericas(self):
		nuevo_estado, datos_temp, respuesta = bot._manejar_metodo_entrega("1", {"items": [{"producto_id": 1}]})
		self.assertEqual(nuevo_estado, "solicitar_ubicacion")
		self.assertEqual(datos_temp.get("metodo_entrega"), "domicilio")
		self.assertIn("direccion", respuesta["contenido"].lower())

		nuevo_estado, datos_temp, _ = bot._manejar_metodo_entrega("2", {"items": [{"producto_id": 1}]})
		self.assertEqual(nuevo_estado, "metodo_pago")
		self.assertEqual(datos_temp.get("metodo_entrega"), "recoger_tienda")

	def test_confirmacion_pide_nombre_sin_sacar_del_cierre(self):
		datos_temp = {
			"items": [{"producto_id": 1, "nombre": "Empanada", "variante": "carne", "cantidad": 2, "precio_unit": 35}],
			"total": 70,
			"metodo_entrega": "domicilio",
			"direccion_id": 9,
			"direccion_texto": "Esteban Hernandez 9349 CP:32695",
			"codigo_postal": "32695",
			"metodo_pago": "efectivo",
			"requiere_factura": False,
		}
		cliente = {"cliente_id": 77, "whatsapp_id": "5210000000000", "nombre": "Cliente"}

		nuevo_estado, nuevos_datos, respuesta = bot._manejar_confirmacion("confirmar", datos_temp, cliente)

		self.assertEqual(nuevo_estado, "completado")
		self.assertEqual(nuevos_datos.get("metodo_pago"), "efectivo")
		self.assertIn("nombre", respuesta["contenido"].lower())

	def test_handle_bienvenida_no_confirma_pedido_viejo_solo_por_recibir_nombre(self):
		sesion = {
			"estado": "bienvenida",
			"datos_temp": {
				"items": [{"producto_id": 1, "nombre": "Empanada", "variante": "carne", "cantidad": 2, "precio_unit": 35}],
				"total": 70,
				"metodo_entrega": "domicilio",
				"direccion_id": 9,
				"direccion_texto": "Esteban Hernandez 9349 CP:32695",
				"codigo_postal": "32695",
				"metodo_pago": "efectivo",
				"requiere_factura": False,
			}
		}
		cliente = {"cliente_id": 77, "whatsapp_id": "5210000000000", "nombre": "Cliente"}

		with patch.object(bot.db, "crear_pedido_completo", side_effect=AssertionError("No debe confirmar pedido viejo solo por recibir el nombre")):
			out = bot.handle_bienvenida(sesion, "Samantha Luna", cliente)

		self.assertEqual(out["nuevo_estado"], "bienvenida")
		self.assertIn("1) Quiero pedir empanadas", out["texto"])

	def test_handle_bienvenida_registra_nombre_y_reanuda_cierre(self):
		sesion = {
			"estado": "bienvenida",
			"datos_temp": {
				"items": [{"producto_id": 1, "nombre": "Empanada", "variante": "carne", "cantidad": 2, "precio_unit": 35}],
				"total": 70,
				"metodo_entrega": "domicilio",
				"direccion_id": 9,
				"direccion_texto": "Esteban Hernandez 9349 CP:32695",
				"codigo_postal": "32695",
				"metodo_pago": "efectivo",
				"requiere_factura": False,
				"esperando_nombre_confirmacion": True,
			}
		}
		cliente = {"cliente_id": 77, "whatsapp_id": "5210000000000", "nombre": "Cliente"}

		with patch.object(bot, "_persistir_datos_cliente"), patch.object(bot.db, "crear_pedido_completo", return_value={"pedido_id": 456, "codigo_entrega": "ZXC789"}):
			out = bot.handle_bienvenida(sesion, "Michelle Aranda", cliente)

		self.assertEqual(out["nuevo_estado"], "completado")
		self.assertEqual(out["datos_temp"]["pedido_id"], 456)
		self.assertEqual(out["datos_temp"]["codigo_entrega"], "ZXC789")

	def test_process_message_estado_inicio_pide_nombre_antes_de_menu(self):
		cliente = {"cliente_id": 77, "whatsapp_id": "5210000000000", "nombre": ""}
		with patch.object(bot.db, "limpiar_sesiones_expiradas"), patch.object(bot, "_obtener_o_crear_cliente", return_value=cliente), patch.object(bot, "_obtener_sesion", return_value={"estado": "inicio", "datos_temp": {}}), patch.object(bot, "_guardar_sesion"):
			out = bot.process_message("5210000000000", "texto", "quiero pedir empanadas")

		self.assertEqual(out["nuevo_estado"], "bienvenida")
		self.assertIn("nombre", out["texto"].lower())
		self.assertNotIn("digame que va a querer", out["texto"].lower())

	def test_manejar_inicio_limpia_pedido_anterior_antes_de_pedir_nombre(self):
		datos_previos = {
			"items": [{"producto_id": 1, "nombre": "Empanada", "cantidad": 2, "precio_unit": 35}],
			"producto_id": 1,
			"cantidad": 2,
			"metodo_entrega": "domicilio",
			"direccion_id": 9,
			"codigo_postal": "32695",
			"metodo_pago": "efectivo",
			"pedido_id": 20,
			"pedido_confirmado": True,
		}

		nuevo_estado, nuevos_datos, respuesta = bot._manejar_inicio("hola", datos_previos, {"cliente_id": 77})

		self.assertEqual(nuevo_estado, "bienvenida")
		self.assertIn("nombre", respuesta["contenido"].lower())
		self.assertFalse(nuevos_datos.get("items"))
		self.assertIsNone(nuevos_datos.get("pedido_id"))
		self.assertIsNone(nuevos_datos.get("metodo_pago"))

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

	def test_handle_completado_conserva_carrito_confirmado_en_sesion(self):
		sesion = {
			"datos_temp": {
				"items": [
					{"producto_id": 1, "nombre": "Empanada", "variante": "carne", "cantidad": 2, "precio_unit": 35},
					{"producto_id": 3, "nombre": "Agua", "variante": "500ml botella", "cantidad": 1, "precio_unit": 15},
				],
				"total": 85,
				"metodo_entrega": "domicilio",
				"metodo_pago": "efectivo",
				"requiere_factura": False,
				"cliente_nombre": "Ana Torres",
			}
		}
		cliente = {"cliente_id": 77, "whatsapp_id": "5210000000000", "nombre": "Ana Torres"}

		with patch.object(bot, "_persistir_datos_cliente"), patch.object(bot.db, "crear_pedido_completo", return_value={"pedido_id": 987, "codigo_entrega": "KLM321"}):
			out = bot.handle_completado(sesion, "confirmar", cliente)

		self.assertEqual(out["nuevo_estado"], "completado")
		self.assertEqual(out["datos_temp"].get("pedido_id"), 987)
		self.assertEqual(out["datos_temp"].get("codigo_entrega"), "KLM321")
		self.assertTrue(out["datos_temp"].get("pedido_confirmado"))
		self.assertEqual(len(out["datos_temp"].get("items") or []), 2)
		self.assertEqual(out["datos_temp"].get("total"), 85)
		self.assertIn("quickchart.io/qr", str(out["datos_temp"].get("qr_url") or ""))

	def test_procesar_mensaje_whatsapp_expone_qr_url_en_confirmacion(self):
		with patch.object(bot, "process_message", return_value={
			"texto": "Pedido confirmado",
			"audio_path": None,
			"audio_colombiano_path": None,
			"qr_url": "https://quickchart.io/qr?size=420&text=QC",
		}):
			out = bot.procesar_mensaje_whatsapp("5210000000000", "confirmar")

		self.assertEqual(out.get("tipo"), "texto")
		self.assertIn("quickchart.io/qr", str(out.get("qr_url") or ""))

	def test_repetir_compra_ofrece_opcion_ultimo_domicilio(self):
		sesion = {"estado": "bienvenida", "datos_temp": {}}
		cliente = {"cliente_id": 33, "whatsapp_id": "117707940831245", "nombre": "Te Ira Biennn"}
		contexto = {
			"ultimo_items": [
				{"nombre": "Empanada", "cantidad": 2, "variante": "carne", "precio_unit": 35.0, "producto_id": 1},
			],
			"ultima_direccion": {
				"direccion_id": 10,
				"codigo_postal": "32695",
				"direccion_texto": "Esteban Hernandez 9349 CP:32695",
			},
		}

		with patch.object(bot, "_obtener_contexto_cliente", return_value=contexto), patch.object(bot, "_validar_items_carrito", return_value=None), patch.object(bot, "_formatear_carrito", return_value="- 2x Empanada carne $70.00\nTOTAL: $70 MXN"):
			out = bot.handle_bienvenida(sesion, "4", cliente)

		self.assertEqual(out["nuevo_estado"], "confirmar_carrito")
		self.assertIn("3) Usar mi ultimo domicilio guardado", out["texto"])

	def test_confirmar_carrito_opcion_ultimo_domicilio_va_a_metodo_pago(self):
		sesion = {
			"estado": "confirmar_carrito",
			"datos_temp": {
				"items": [{"producto_id": 1, "cantidad": 2, "precio_unit": 35.0}],
				"total": 70,
				"contexto_cliente": {
					"ultima_direccion": {
						"direccion_id": 10,
						"codigo_postal": "32695",
						"direccion_texto": "Esteban Hernandez 9349 CP:32695",
					}
				},
			},
		}
		cliente = {"cliente_id": 33, "whatsapp_id": "117707940831245", "nombre": "Te Ira Biennn"}

		out = bot.handle_confirmar_carrito(sesion, "3", cliente)

		self.assertEqual(out["nuevo_estado"], "metodo_pago")
		self.assertEqual(out["datos_temp"].get("metodo_entrega"), "domicilio")
		self.assertEqual(out["datos_temp"].get("direccion_id"), 10)
		self.assertIn("domicilio guardado", out["texto"].lower())


if __name__ == "__main__":
	unittest.main()