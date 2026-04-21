import os
import sys
import unittest
from datetime import datetime
from flask import Flask


CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import db
from routes.report_routes import register_report_routes


class FinancialAuditHelpersTest(unittest.TestCase):
    def test_normaliza_metodos_pago_financieros(self):
        self.assertEqual(db._normalizar_metodo_pago_finanzas("Efectivo"), "efectivo")
        self.assertEqual(db._normalizar_metodo_pago_finanzas("mercado pago"), "mercadopago")
        self.assertEqual(db._normalizar_metodo_pago_finanzas("contra_entrega_ficticio"), "contra_entrega")
        self.assertEqual(db._normalizar_metodo_pago_finanzas("tarjeta"), "digital")
        self.assertEqual(db._normalizar_metodo_pago_finanzas(""), "sin_definir")

    def test_clasifica_turno_operativo(self):
        self.assertEqual(db._clasificar_turno_operativo(datetime(2026, 4, 14, 8, 30)), "manana")
        self.assertEqual(db._clasificar_turno_operativo(datetime(2026, 4, 14, 15, 0)), "tarde")
        self.assertEqual(db._clasificar_turno_operativo(datetime(2026, 4, 14, 22, 15)), "noche")

    def test_clasifica_estatus_factura_profesional(self):
        self.assertEqual(db._clasificar_estado_factura_finanzas(False, None, "recibido"), "no_requiere")
        self.assertEqual(db._clasificar_estado_factura_finanzas(True, None, "recibido"), "pendiente_datos")
        self.assertEqual(db._clasificar_estado_factura_finanzas(True, 22, "en_preparacion"), "lista_para_emision")
        self.assertEqual(db._clasificar_estado_factura_finanzas(True, 22, "entregado"), "lista_para_entrega")
        self.assertEqual(db._clasificar_estado_factura_finanzas(True, 22, "entregado", "emitida"), "emitida")
        self.assertEqual(db._clasificar_estado_factura_finanzas(True, 22, "entregado", "entregada"), "entregada")

    def test_evalua_cobranza_real_efectivo_y_tarjeta(self):
        cash = db._evaluar_cobranza_pedido_finanzas(
            metodo_pago="efectivo",
            estado_pedido="entregado",
            total=250,
            monto_pagado=0,
            estados_pago="",
        )
        self.assertEqual(cash["status"], "validado")
        self.assertEqual(cash["monto_validado"], 250.0)
        self.assertEqual(cash["pendiente"], 0.0)

        tarjeta_parcial = db._evaluar_cobranza_pedido_finanzas(
            metodo_pago="tarjeta",
            estado_pedido="entregado",
            total=300,
            monto_pagado=120,
            estados_pago="pending",
        )
        self.assertEqual(tarjeta_parcial["status"], "parcial")
        self.assertEqual(tarjeta_parcial["monto_validado"], 120.0)
        self.assertEqual(tarjeta_parcial["pendiente"], 180.0)

        tarjeta_ok = db._evaluar_cobranza_pedido_finanzas(
            metodo_pago="mercadopago",
            estado_pedido="recibido",
            total=300,
            monto_pagado=300,
            estados_pago="approved",
        )
        self.assertEqual(tarjeta_ok["status"], "validado")
        self.assertEqual(tarjeta_ok["pendiente"], 0.0)

    def test_clasifica_salud_de_producto_con_coherencia(self):
        self.assertEqual(db._clasificar_salud_producto_rentabilidad(100, 0, "sin_receta"), "sin_receta")
        self.assertEqual(db._clasificar_salud_producto_rentabilidad(100, 0, "sin_costos"), "sin_costos")
        self.assertEqual(db._clasificar_salud_producto_rentabilidad(100, 120, "completo"), "sin_utilidad")
        self.assertEqual(db._clasificar_salud_producto_rentabilidad(100, 85, "completo"), "margen_bajo")
        self.assertEqual(db._clasificar_salud_producto_rentabilidad(100, 45, "completo"), "rentable")

    def test_resume_coherencia_general_de_productos(self):
        resumen = db._resumir_coherencia_productos([
            {"calidad_costo": "sin_receta", "precio_venta": 35, "costo_estimado_unitario": 0},
            {"calidad_costo": "sin_costos", "precio_venta": 40, "costo_estimado_unitario": 0},
            {"calidad_costo": "completo", "precio_venta": 50, "costo_estimado_unitario": 55},
            {"calidad_costo": "completo", "precio_venta": 60, "costo_estimado_unitario": 15},
        ])
        self.assertEqual(resumen["productos_sin_receta"], 1)
        self.assertEqual(resumen["productos_sin_costos"], 1)
        self.assertEqual(resumen["productos_sin_utilidad"], 1)
        self.assertEqual(resumen["productos_rentables"], 1)


class FinancialAuditRouteRegressionTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.invoice_calls = []
        self.fake_payload = {
            "fecha_base": "2026-04-14",
            "costos": {"resumen": {"productos_auditados": 3}, "rows": []},
            "facturacion_pagos": {"resumen": {"pedidos": 4}, "rows": []},
            "corte_caja": {"resumen": {"turnos": 3}, "rows": []},
        }

        outer = self

        class FakeDb:
            def obtener_auditoria_financiera(self, fecha_base=None, limit=50):
                outer.calls.append({"fecha_base": fecha_base, "limit": limit})
                return outer.fake_payload

            def registrar_factura_operativa(self, **payload):
                outer.invoice_calls.append(payload)
                return {
                    "pedido_id": payload.get("pedido_id"),
                    "folio_factura": payload.get("folio_factura"),
                    "status": payload.get("status") or "entregada",
                    "email_destino": "cliente@example.com",
                }

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
        register_report_routes(app, {
            "db": FakeDb(),
            "ok": ok,
            "error": error,
            "login_required": login_required,
            "serialize": lambda payload: payload,
        })
        self.app = app

    def test_financial_audit_endpoint_forwards_filters(self):
        with self.app.test_request_context("/api/admin/finanzas/auditoria?fecha=2026-04-14&limit=80"):
            response = self.app.view_functions["api_admin_financial_audit"]()

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["data"], self.fake_payload)
        self.assertEqual(self.calls, [{"fecha_base": "2026-04-14", "limit": 80}])

        body = {
            "pedido_id": 455,
            "folio_factura": "FOL-20260414-001",
            "status": "entregada",
            "notas": "enviada al correo del cliente"
        }
        with self.app.test_request_context("/api/admin/finanzas/factura", method="POST", json=body):
            response = self.app.view_functions["api_admin_invoice_delivery"]()

        self.assertEqual(response["status"], 200)
        self.assertEqual(self.invoice_calls[0]["pedido_id"], 455)
        self.assertEqual(self.invoice_calls[0]["folio_factura"], "FOL-20260414-001")
        self.assertEqual(response["data"]["status"], "entregada")


if __name__ == "__main__":
    unittest.main()
