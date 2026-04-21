import os
import sys
import unittest
from flask import Flask


CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from routes.webhook_routes import register_webhook_routes


class _FakeMsg:
    def __init__(self):
        self._body = ""
        self._media = []

    def body(self, text):
        self._body = str(text)

    def media(self, url):
        self._media.append(str(url))


class _FakeTwiml:
    def __init__(self):
        self._msg = _FakeMsg()

    def message(self):
        return self._msg

    def __str__(self):
        return "<Response><Message>ok</Message></Response>"


class WebhookSecurityRegressionTest(unittest.TestCase):
    def setUp(self):
        def ok(data, status=200):
            return {"data": data, "status": status}

        def error(message, status=400, code=None, details=None):
            return {"error": message, "status": status, "code": code, "details": details}

        app = Flask(__name__)
        app.testing = True
        app.config["WHATSAPP_LEGACY_WEBHOOK_TOKEN"] = "token-demo"
        app.config["MP_WEBHOOK_TOKEN"] = "mp-token-demo"

        deps = {
            "ok": ok,
            "error": error,
            "normalize_whatsapp_id": lambda value: str(value or "").replace("whatsapp:", "").strip(),
            "procesar_mensaje_whatsapp": lambda **kwargs: {"tipo": "texto", "contenido": "ok"},
            "messaging_response_cls": _FakeTwiml,
            "send_audio_whatsapp": lambda destino, path: {"ok": True},
            "verify_payment_status": lambda payment_id: {
                "payment_id": str(payment_id),
                "status": "approved",
                "external_reference": "123",
            },
        }
        register_webhook_routes(app, deps)
        self.app = app

    def test_legacy_webhook_rejects_missing_token(self):
        with self.app.test_request_context(
            "/webhook",
            method="POST",
            data={"From": "whatsapp:+5216561234567", "Body": "hola"},
        ):
            response = self.app.view_functions["webhook_whatsapp"]()

        self.assertEqual(response["status"], 401)

    def test_legacy_webhook_accepts_query_token(self):
        with self.app.test_request_context(
            "/webhook?token=token-demo",
            method="POST",
            data={"From": "whatsapp:+5216561234567", "Body": "hola"},
        ):
            response = self.app.view_functions["webhook_whatsapp"]()

        self.assertEqual(response[1], 200)

    def test_payment_webhook_rejects_missing_token(self):
        with self.app.test_request_context(
            "/webhook/pago",
            method="POST",
            json={"data": {"id": "123456"}},
        ):
            response = self.app.view_functions["webhook_pago"]()

        self.assertEqual(response["status"], 401)

    def test_payment_webhook_accepts_and_processes_valid_id(self):
        with self.app.test_request_context(
            "/webhook/pago?token=mp-token-demo",
            method="POST",
            json={"data": {"id": "123456"}},
        ):
            response = self.app.view_functions["webhook_pago"]()

        self.assertEqual(response["status"], 200)
        self.assertTrue(response["data"]["processed"])
        self.assertEqual(response["data"]["payment_id"], "123456")


if __name__ == "__main__":
    unittest.main()
