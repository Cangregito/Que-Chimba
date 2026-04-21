#!/usr/bin/env python3
"""
Test de Integración: PDF + WhatsApp para Facturas
Verifica que el flujo completo funcione correctamente
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Mock minimal para testing
class MockDb:
    def obtener_pedido_por_id(self, pedido_id):
        return {
            "pedido_id": pedido_id,
            "cliente_id": 1,
            "datos_fiscales_id": 1,
            "total": 50000.00,
            "creado_en": datetime.now().isoformat()
        }
    
    def obtener_cliente_por_id(self, cliente_id):
        return {
            "cliente_id": cliente_id,
            "nombre": "Juan",
            "apellidos": "Pérez",
            "whatsapp_id": "+573051234567"
        }
    
    def obtener_datos_fiscales_por_id(self, datos_fiscales_id):
        return {
            "datos_fiscales_id": datos_fiscales_id,
            "rfc": "JUPA850101ABC",
            "razon_social": "Juan Pérez",
            "regimen_fiscal": "601",
            "uso_cfdi": "G01",
            "email": "juan@example.com"
        }
    
    def obtener_items_pedido(self, pedido_id):
        return [
            {
                "detalle_id": 1,
                "producto_id": 1,
                "cantidad": 2,
                "precio_unitario": 25000.00,
                "subtotal": 50000.00,
                "producto_nombre": "Empanadas de Carne",
                "descripcion": "Empanada tradicional 200g"
            }
        ]
    
    def registrar_auditoria_factura(self, **kwargs):
        print(f"✅ Auditoría registrada: {kwargs.get('evento_tipo')}")


def test_pdf_generation():
    """Test: Generación de PDF"""
    print("\n" + "="*60)
    print("TEST 1: Generación de PDF")
    print("="*60)
    
    try:
        from bot_empanadas.services.pdf_service import generar_pdf_factura
        
        pdf_result = generar_pdf_factura(
            pedido_id=42,
            folio_factura="TEST-001",
            datos_cliente={
                "nombre": "Juan",
                "apellidos": "Pérez",
                "whatsapp_id": "+573051234567"
            },
            datos_fiscales={
                "rfc": "JUPA850101ABC",
                "razon_social": "Juan Pérez",
                "regimen_fiscal": "601",
                "uso_cfdi": "G01",
                "email": "juan@example.com"
            },
            items_pedido=[
                {
                    "producto_nombre": "Empanadas",
                    "cantidad": 2,
                    "precio_unitario": 25000.00,
                    "subtotal": 50000.00
                }
            ],
            total=50000.00,
            empresa_nombre="QUE CHIMBA",
            empresa_rfc="QUI123456ABC"
        )
        
        if "error" not in pdf_result:
            print(f"✅ PDF Generado: {pdf_result.get('ruta')}")
            print(f"   Folio: {pdf_result.get('folio')}")
            print(f"   Total: {pdf_result.get('total')}")
            print(f"   Fecha: {pdf_result.get('fecha_generacion')}")
            
            # Verificar que el archivo existe
            pdf_path = Path(pdf_result.get('ruta'))
            if pdf_path.exists():
                size = pdf_path.stat().st_size
                print(f"   Tamaño: {size} bytes ✅")
                return True
            else:
                print(f"   ❌ Archivo no encontrado en disco")
                return False
        else:
            print(f"❌ Error generando PDF: {pdf_result['error']}")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_whatsapp_function_exists():
    """Test: Función de WhatsApp existe y es callable"""
    print("\n" + "="*60)
    print("TEST 2: Función send_document_whatsapp existe")
    print("="*60)
    
    try:
        from bot_empanadas.services.whatsapp_service import send_document_whatsapp
        
        if callable(send_document_whatsapp):
            print("✅ Función send_document_whatsapp es importable y callable")
            
            # Verificar signature
            import inspect
            sig = inspect.signature(send_document_whatsapp)
            params = list(sig.parameters.keys())
            print(f"   Parámetros: {params}")
            
            expected = ["app", "destino", "documento_path", "caption", "default_public_base_url"]
            if all(p in params or p.startswith("**") for p in expected[:3]):
                print("   ✅ Parámetros correctos")
                return True
            else:
                print(f"   ❌ Parámetros incorrectos. Esperados: {expected}")
                return False
        else:
            print("❌ send_document_whatsapp no es callable")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


def test_db_functions():
    """Test: Nuevas funciones en db.py existen"""
    print("\n" + "="*60)
    print("TEST 3: Nuevas funciones en db.py")
    print("="*60)
    
    functions_to_check = [
        "obtener_pedido_por_id",
        "obtener_cliente_por_id",
        "obtener_datos_fiscales_por_id",
        "obtener_items_pedido"
    ]
    
    all_ok = True
    try:
        from bot_empanadas import db
        
        for func_name in functions_to_check:
            if hasattr(db, func_name) and callable(getattr(db, func_name)):
                print(f"✅ {func_name}")
            else:
                print(f"❌ {func_name} - NO ENCONTRADA")
                all_ok = False
        
        return all_ok
        
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


def test_imports():
    """Test: Todos los imports necesarios funcionan"""
    print("\n" + "="*60)
    print("TEST 4: Imports y dependencias")
    print("="*60)
    
    imports_to_test = [
        ("reportlab.lib.pagesizes", "letter"),
        ("reportlab.lib.styles", "getSampleStyleSheet"),
        ("reportlab.platypus", "SimpleDocTemplate"),
        ("flask", "Flask"),
        ("pathlib", "Path"),
    ]
    
    all_ok = True
    for module_path, item in imports_to_test:
        try:
            parts = module_path.split(".")
            module = __import__(module_path)
            for part in parts[1:]:
                module = getattr(module, part)
            
            if item:
                obj = getattr(module, item)
                print(f"✅ from {module_path} import {item}")
            else:
                print(f"✅ import {module_path}")
        except Exception as e:
            print(f"❌ {module_path}.{item} - {e}")
            all_ok = False
    
    return all_ok


def test_requirements_updated():
    """Test: requirements.txt tiene reportlab"""
    print("\n" + "="*60)
    print("TEST 5: requirements.txt actualizado")
    print("="*60)
    
    try:
        # Buscar requirements.txt en bot_empanadas/
        req_path = Path(__file__).parent / "bot_empanadas" / "requirements.txt"
        if not req_path.exists():
            # Intentar en la raíz
            req_path = Path(__file__).parent / "requirements.txt"
        if not req_path.exists():
            print(f"❌ requirements.txt no encontrado")
            return False
        
        content = req_path.read_text()
        if "reportlab" in content:
            print("✅ reportlab está en requirements.txt")
            # Extract version
            for line in content.split("\n"):
                if "reportlab" in line:
                    print(f"   {line.strip()}")
            return True
        else:
            print("❌ reportlab NO está en requirements.txt")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


def main():
    """Ejecuta todos los tests"""
    print("\n" + "🧪 SUITE DE TESTS: Integración PDF + WhatsApp")
    print("="*60)
    
    results = []
    
    # Test 1: Imports
    results.append(("Imports/Dependencies", test_imports()))
    
    # Test 2: Requirements
    results.append(("requirements.txt", test_requirements_updated()))
    
    # Test 3: DB Functions
    results.append(("DB Functions", test_db_functions()))
    
    # Test 4: WhatsApp Function
    results.append(("WhatsApp Function", test_whatsapp_function_exists()))
    
    # Test 5: PDF Generation (requiere reportlab)
    if results[0][1]:  # Solo si imports OK
        results.append(("PDF Generation", test_pdf_generation()))
    
    # Resumen
    print("\n" + "="*60)
    print("📊 RESUMEN DE RESULTADOS")
    print("="*60)
    
    total = len(results)
    passed = sum(1 for _, result in results if result)
    failed = total - passed
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:10} {test_name}")
    
    print("-" * 60)
    print(f"Total: {total} tests")
    print(f"Pasados: {passed} ✅")
    print(f"Fallidos: {failed} ❌")
    
    if failed == 0:
        print("\n🎉 TODOS LOS TESTS PASARON")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) fallido(s)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
