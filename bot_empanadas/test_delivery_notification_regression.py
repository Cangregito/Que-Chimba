import os
import sys
import unittest
from flask import Flask


CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from routes.order_routes import register_order_routes


class DeliveryNotificationRegressionTest(unittest.TestCase):
    def setUp(self):
        self.sent_messages = []
        self.logged_notifications = []

        class FakeDb:
            def actualizar_estado_pedido(self, pedido_id, nuevo_estado, actor_usuario=None, rol_actor=None, motivo=None):
                return {"pedido_id": pedido_id, "estado": nuevo_estado, "creado_en": "2026-04-14T18:19:48"}

            def confirmar_entrega_pedido(self, **kwargs):
                return {"pedido_id": kwargs["pedido_id"], "estado": "entregado"}

            def obtener_destino_whatsapp_por_pedido(self, pedido_id):
                return {"whatsapp_id": "1234567890"}

            def crear_log_notificacion(self, payload):
                self_outer.logged_notifications.append(payload)
                return {"ok": True}

        self_outer = self
        fake_db = FakeDb()

        def login_required(roles=None):
            def decorator(fn):
                return fn
            return decorator

        def ok(data, status=200):
            return {"data": data, "status": status}

        def error(message, status=400, code=None, details=None):
            return {"error": message, "status": status, "code": code, "details": details}

        def validar_requeridos(payload, required_fields):
            return [field for field in required_fields if not payload.get(field)]

        def send_text_whatsapp(destino, texto):
            self.sent_messages.append({"destino": destino, "texto": texto})
            return {"ok": True}

        app = Flask(__name__)
        app.testing = True

        deps = {
            "db": fake_db,
            "ok": ok,
            "error": error,
            "login_required": login_required,
            "validar_requeridos": validar_requeridos,
            "estados_validos_pedido": {"recibido", "en_preparacion", "listo", "en_camino", "entregado", "cancelado"},
            "send_text_whatsapp": send_text_whatsapp,
            "normalize_whatsapp_id": lambda value: (value or "").strip(),
            "normalize_ticket_destination": lambda value: f"52{''.join(ch for ch in str(value) if ch.isdigit())}"[-12:],
        }
        register_order_routes(app, deps)
        self.app = app

    def test_confirmar_entrega_normaliza_destino_para_notificacion(self):
        with self.app.test_request_context(json={"codigo_entrega": "ABC123"}):
            response = self.app.view_functions["api_confirmar_entrega_pedido"](321)

        data = response["data"]
        self.assertTrue(data["notificacion_cliente"]["enviado"])
        self.assertEqual(self.sent_messages[0]["destino"], "521234567890")
        self.assertEqual(data["notificacion_cliente"]["destino"], "521234567890")
        self.assertEqual(self.logged_notifications[0]["tipo"], "agradecimiento_entrega")

    def test_actualizar_estado_en_preparacion_envia_confirmacion_al_cliente(self):
        with self.app.test_request_context(json={"estado": "en_preparacion"}):
            response = self.app.view_functions["api_actualizar_estado_pedido"](21)

        data = response["data"]
        self.assertTrue(data["notificacion_cliente"]["enviado"])
        self.assertEqual(self.sent_messages[0]["destino"], "521234567890")
        self.assertIn("pedido #21", self.sent_messages[0]["texto"].lower())
        self.assertEqual(self.logged_notifications[0]["tipo"], "confirmacion_recepcion")


class DeliveryUiQrRegressionTest(unittest.TestCase):
    def test_template_permite_fallback_manual_si_el_qr_falla(self):
        template_path = os.path.join(CURRENT_DIR, "templates", "repartidor.html")
        with open(template_path, "r", encoding="utf-8") as fh:
            html = fh.read()

        self.assertIn("escribe el codigo de entrega", html)
        self.assertIn("type='text' maxlength='12' autocomplete='off' placeholder='Codigo de entrega'", html)
        self.assertIn("window.stopQrScanner = stopQrScanner;", html)


if __name__ == "__main__":
    unittest.main()
