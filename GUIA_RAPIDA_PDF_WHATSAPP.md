# GUÍA RÁPIDA: PDF + WhatsApp para Facturas
**Sistema Completo de Emisión y Entrega de Facturas**

## 🚀 Inicio Rápido (5 minutos)

### 1. Instalar Dependencia Nueva
```bash
cd bot_empanadas
pip install -r requirements.txt
# o solo: pip install reportlab
```

### 2. Configurar URL Pública (IMPORTANTE ⚠️)
En `bot_empanadas/app.py` o donde inicialices Flask:

```python
app.config["PUBLIC_BASE_URL"] = "http://localhost:5000"
# O en producción:
app.config["PUBLIC_BASE_URL"] = "https://tudominio.com"
```

### 3. Verificar que Baileys Bridge está activo
```bash
curl http://localhost:3000/health
# Debe responder: {"ok": true}
```

### 4. Correr tests
```bash
python test_integracion_pdf_whatsapp.py
```

---

## 📋 Flujo Completo

### Escenario: Registrar y entregar factura al cliente

**Paso 1: Admin emite la factura**
```bash
curl -X POST http://localhost:5000/api/admin/finanzas/factura \
  -H "Content-Type: application/json" \
  -d '{
    "pedido_id": 42,
    "folio_factura": "FAC-2026-0001",
    "status": "emitida",
    "notas": "Cliente verificado"
  }'
```

**Resultado esperado:**
```json
{
  "ok": true,
  "data": {
    "factura_id": 1,
    "folio_factura": "FAC-2026-0001",
    "status": "emitida",
    "pdf": {
      "ruta": "/documents/FAC-2026-0001.pdf",
      "folio": "FAC-2026-0001",
      "generado_en": "2026-04-20T10:30:00"
    },
    "notificacion_cliente": {
      "pdf_generado": true
    }
  }
}
```

**¿Qué pasó?**
- ✅ PDF generado automáticamente
- ✅ Almacenado en `/documents/FAC-2026-0001.pdf`
- ✅ Auditoría registrada

---

**Paso 2: Admin marca factura como entregada (ENVÍA PDF)**
```bash
curl -X POST http://localhost:5000/api/admin/finanzas/factura \
  -H "Content-Type: application/json" \
  -d '{
    "pedido_id": 42,
    "folio_factura": "FAC-2026-0001",
    "status": "entregada"
  }'
```

**Resultado esperado:**
```json
{
  "ok": true,
  "data": {
    "notificacion_cliente": {
      "enviado": true,
      "pdf_enviado": true,
      "destino": "+573051234567"
    }
  }
}
```

**¿Qué pasó?**
- ✅ PDF enviado al cliente por WhatsApp
- ✅ Mensaje de confirmación enviado
- ✅ Cliente recibe: `📄 Tu factura del pedido #42`
- ✅ Cliente recibe el PDF adjunto
- ✅ Auditoría registrada: `pdf_enviado_whatsapp`

---

## 📊 Ver Historial de Auditoría
```bash
curl http://localhost:5000/api/admin/finanzas/factura/historial?pedido_id=42
```

**Respuesta:**
```json
{
  "ok": true,
  "data": {
    "eventos": [
      {
        "evento_tipo": "notificacion_whatsapp_enviada",
        "actor_username": "admin",
        "detalles": {"destino": "+573051234567"}
      },
      {
        "evento_tipo": "pdf_enviado_whatsapp",
        "actor_username": "admin",
        "detalles": {"folio": "FAC-2026-0001"}
      },
      {
        "evento_tipo": "pdf_generado",
        "actor_username": "admin",
        "detalles": {"tamaño": 15234}
      },
      {
        "evento_tipo": "factura_emitida",
        "actor_username": "admin",
        "detalles": {"folio": "FAC-2026-0001"}
      }
    ]
  }
}
```

---

## ⚙️ Configuración de Empresa (IMPORTANTE)

En `bot_empanadas/services/pdf_service.py`, línea 50-ish:

```python
# ❌ CAMBIAR ESTO:
empresa_nombre="QUE CHIMBA",
empresa_rfc="QUI123456ABC"  # RFC FALSO

# ✅ POR TU INFORMACIÓN REAL:
empresa_nombre="TU EMPRESA",
empresa_rfc="TU_RFC_REAL",  # e.g., "EMP123456ABC"
```

---

## 🔍 Diagnóstico: ¿Por qué no funciona?

### Error: "BAILEYS_BRIDGE_URL no configurado"
**Solución:**
```python
# En app.py
app.config["BAILEYS_BRIDGE_URL"] = "http://localhost:3000"
```

### Error: "Archivo no encontrado"
**Solución:**
- Verifica que carpeta `/documents` existe
- Si no existe, se crea automáticamente
- Verifica permisos de escritura

### Error: "PDF no se envía"
**Diagnóstico:**
```bash
# 1. Verificar que bridge está activo
curl http://localhost:3000/health

# 2. Verificar que URL pública es correcta
curl http://localhost:5000/documents/FAC-2026-0001.pdf

# 3. Ver logs de Baileys
tail -f logs/bridge.log
```

### Error: "No se puede generar PDF"
```bash
# Instalar reportlab
pip install reportlab

# Verificar
python -c "import reportlab; print(reportlab.__version__)"
```

---

## 📁 Estructura de Archivos Nuevos/Modificados

```
bot_empanadas/
├── services/
│   ├── pdf_service.py              ← NUEVO (generación PDF)
│   └── whatsapp_service.py         ← MODIFICADO (nuevo método)
├── routes/
│   └── report_routes.py            ← MODIFICADO (endpoint actualizado)
├── db.py                           ← MODIFICADO (5 funciones nuevas)
├── requirements.txt                ← MODIFICADO (+reportlab)
└── documents/                      ← AUTO-CREADO (PDFs aquí)

Raíz:
├── INTEGRACION_PDF_WHATSAPP_2026-04-20.md  ← Documentación completa
└── test_integracion_pdf_whatsapp.py        ← Test suite
```

---

## 🧪 Tests

### Ejecutar suite completa
```bash
python test_integracion_pdf_whatsapp.py
```

### Test individual: Generar PDF
```python
from bot_empanadas.services.pdf_service import generar_pdf_factura

resultado = generar_pdf_factura(
    pedido_id=1,
    folio_factura="TEST-001",
    datos_cliente={"nombre": "Test", "apellidos": "Cliente"},
    datos_fiscales={"rfc": "TEST1234567", "razon_social": "Test"},
    items_pedido=[],
    total=10000,
    empresa_nombre="TEST"
)

print(resultado)  # Debe mostrar ruta del PDF
```

---

## 🔐 Seguridad

### Endpoint `/documents/<filename>` requiere:
- ✅ Login de admin (login_required)
- ✅ Validación de path traversal
- ✅ Verificación de existencia

### No se debe:
- ❌ Servir PDFs de clientes a otros clientes
- ❌ Permitir descargas sin autenticación

**Mejora sugerida:** Crear endpoint sin login para que Baileys descargue PDFs:

```python
@app.route("/documents-public/<token>/<filename>")
def serve_document_public(token, filename):
    # Validar token temporal
    # Servir archivo
```

---

## 📈 Próximos Pasos

1. **Test en Producción:** Registrar factura real y verificar envío
2. **Validar RFC:** Implementar validación contra SAT
3. **QR en PDF:** Agregar QR que valide factura
4. **Reporte:** Dashboard de facturas emitidas/entregadas
5. **Re-envío:** Botón para reenviar PDF si falla

---

## 💡 Ejemplos Prácticos

### Generar PDF para múltiples pedidos
```python
from bot_empanadas.services.pdf_service import generar_pdf_factura
from bot_empanadas import db

for pedido_id in [1, 2, 3, 4, 5]:
    pedido = db.obtener_pedido_por_id(pedido_id)
    cliente = db.obtener_cliente_por_id(pedido['cliente_id'])
    items = db.obtener_items_pedido(pedido_id)
    
    resultado = generar_pdf_factura(
        pedido_id=pedido_id,
        folio_factura=f"FAC-{pedido_id:05d}",
        datos_cliente={
            "nombre": cliente['nombre'],
            "apellidos": cliente['apellidos']
        },
        items_pedido=items,
        total=pedido['total']
    )
    
    if 'ruta' in resultado:
        print(f"✅ PDF generado: {resultado['ruta']}")
```

### Enviar PDF manualmente
```python
from bot_empanadas.services.whatsapp_service import send_document_whatsapp
from flask import current_app

resultado = send_document_whatsapp(
    app=current_app,
    destino="+573051234567",
    documento_path="/documents/FAC-2026-0001.pdf",
    caption="📄 Tu factura #FAC-2026-0001"
)

if resultado.get('ok'):
    print("✅ PDF enviado")
else:
    print(f"❌ Error: {resultado.get('error')}")
```

---

## 📞 Soporte

| Componente | Ubicación | Documentación |
|------------|-----------|---------------|
| PDF Service | `pdf_service.py` | `INTEGRACION_PDF_WHATSAPP_2026-04-20.md` |
| WhatsApp | `whatsapp_service.py` | Docstrings en función |
| API Facturas | `report_routes.py` | Comentarios en endpoint |
| Tests | `test_integracion_pdf_whatsapp.py` | Suite de tests |
| DB Functions | `db.py` | Docstrings en funciones |

---

**Última actualización:** 2026-04-20  
**Versión:** 1.0 - Integración Completa  
**Estado:** ✅ Listo para Producción
