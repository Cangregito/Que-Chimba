import os
import sys
import unittest
from flask import Flask


CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import bot
import db
from routes.admin_routes import register_admin_routes


class AdminProductCostRouteRegressionTest(unittest.TestCase):
    def setUp(self):
        self.patch_calls = []
        self.post_calls = []
        outer = self

        class FakeDb:
            def obtener_productos_admin(self, limit=200):
                return []

            def crear_producto_manual(self, **payload):
                outer.post_calls.append(payload)
                return {"producto_id": 8, **payload}

            def actualizar_producto_admin(self, **payload):
                outer.patch_calls.append(payload)
                return {"producto_id": payload.get("producto_id"), **payload}

        def login_required(roles=None):
            def decorator(fn):
                return fn
            return decorator

        def ok(data, status=200):
            return {"data": data, "status": status}

        def error(message, status=400, code=None, details=None):
            return {"error": message, "status": status, "code": code, "details": details}

        app = Flask(__name__)
        app.testing = True
        register_admin_routes(app, {
            "db": FakeDb(),
            "ok": ok,
            "error": error,
            "login_required": login_required,
            "client_ip": lambda: "127.0.0.1",
        })
        self.app = app

    def test_patch_producto_admin_forwards_manual_cost(self):
        body = {
            "nombre": "Empanada",
            "variante": "carne",
            "precio": 42,
            "costo_referencia": 18.5,
            "activo": True,
        }
        with self.app.test_request_context("/api/admin/productos/9", method="PATCH", json=body):
            response = self.app.view_functions["api_admin_productos_actualizar"](9)

        self.assertEqual(response["status"], 200)
        self.assertEqual(self.patch_calls[0]["costo_referencia"], 18.5)

    def test_post_producto_admin_accepts_manual_cost(self):
        body = {
            "nombre": "Empanada",
            "variante": "pollo",
            "precio": 39,
            "costo_referencia": 16.75,
            "activo": True,
        }
        with self.app.test_request_context("/api/admin/productos", method="POST", json=body):
            response = self.app.view_functions["api_admin_productos_crear_actualizar"]()

        self.assertEqual(response["status"], 201)
        self.assertEqual(self.post_calls[0]["costo_referencia"], 16.75)


class ClientNameValidationRegressionTest(unittest.TestCase):
    def test_invalid_command_words_are_not_names(self):
        self.assertFalse(bot._nombre_cliente_es_valido("Confirmar"))
        self.assertFalse(bot._nombre_cliente_es_valido("Menu"))
        self.assertFalse(bot._nombre_cliente_es_valido("Pedido"))

    def test_extract_name_ignores_operational_commands(self):
        self.assertIsNone(bot._extraer_nombre_cliente("confirmar"))
        self.assertIsNone(bot._extraer_nombre_cliente("menu"))
        self.assertEqual(bot._extraer_nombre_cliente("me llamo Maria Fernanda"), "Maria Fernanda")

    def test_fake_seeded_numbers_are_detected(self):
        self.assertTrue(db._parece_cliente_temporal("521000000001", "Cliente", "WhatsApp", total_pedidos=0))
        self.assertTrue(db._parece_cliente_temporal("5219991234567", "Validacion", "Final", total_pedidos=1))
        self.assertFalse(db._parece_cliente_temporal("5216565320062", "Maria", "Lopez", total_pedidos=2))


if __name__ == "__main__":
    unittest.main()
