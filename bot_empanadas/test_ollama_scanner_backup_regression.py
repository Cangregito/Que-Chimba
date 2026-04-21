import os
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import bot


class OllamaServerErrorRegressionTest(unittest.TestCase):
    def setUp(self):
        self._old_failures = getattr(bot, "_llm_local_failures", 0)
        self._old_cooldown = getattr(bot, "_llm_local_cooldown_until", 0.0)
        bot._llm_local_failures = 0
        bot._llm_local_cooldown_until = 0.0

    def tearDown(self):
        bot._llm_local_failures = self._old_failures
        bot._llm_local_cooldown_until = self._old_cooldown

    def test_http_500_no_reintenta_en_bucle(self):
        class Http500Error(Exception):
            pass

        bad_response = Mock()
        bad_response.status_code = 500
        bad_response.raise_for_status.side_effect = Http500Error("server 500")

        with patch.object(bot, "requests", create=True) as requests_mock, \
             patch.object(bot, "LLM_LOCAL_RETRIES", 3), \
             patch.object(bot, "LLM_LOCAL_RETRY_BACKOFF_SEC", 0):
            requests_mock.post.return_value = bad_response
            with self.assertRaises(Http500Error):
                bot._post_ollama_generate({"model": "phi3:mini"}, 1.0)

        self.assertEqual(requests_mock.post.call_count, 1, "No debe reintentar multiples veces cuando Ollama ya responde 500")

    def test_pulido_estilo_no_desactiva_ollama_para_conversaciones(self):
        class Http500Error(Exception):
            pass

        bad_response = Mock()
        bad_response.status_code = 500
        bad_response.raise_for_status.side_effect = Http500Error("server 500")

        with patch.object(bot, "requests", create=True) as requests_mock, \
             patch.object(bot, "LLM_STYLE_ENABLED", True), \
             patch.object(bot, "LLM_LOCAL_ENABLED", True), \
             patch.object(bot, "LLM_FALLBACK_ENABLED", False):
            requests_mock.post.return_value = bad_response
            original = "Gracias por escribirnos, te esperamos hoy en sucursal Centro."
            resultado = bot._pulir_texto_con_ia(original, {})

        self.assertEqual(resultado, original, "Si falla el pulido opcional, debe conservar el texto base")
        self.assertEqual(bot._llm_local_failures, 0, "El pulido opcional no debe marcar a Ollama como caido")
        self.assertEqual(bot._llm_local_cooldown_until, 0.0, "El pulido opcional no debe activar cooldown global")


class RepartidorScannerUiRegressionTest(unittest.TestCase):
    def test_repartidor_no_pide_codigo_manual_visible(self):
        template_path = pathlib.Path(__file__).resolve().parent / "templates" / "repartidor.html"
        html = template_path.read_text(encoding="utf-8")
        self.assertNotIn("Ingresa el codigo del cliente", html)
        self.assertIn("Escanea el QR para validar la entrega", html)


class BackupRollbackRegressionTest(unittest.TestCase):
    def test_existe_script_rollback_postgres(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        rollback_script = root / "scripts" / "ops" / "rollback_postgres.ps1"
        self.assertTrue(rollback_script.exists(), "Debe existir un script operativo de rollback")


if __name__ == "__main__":
    unittest.main()
