# ✅ CHECKLIST: Integración PDF + WhatsApp para Facturas

## 📋 Pre-Requisitos
- [ ] Python 3.8+ instalado
- [ ] Flask app funcionando
- [ ] PostgreSQL 16+ en uso
- [ ] Baileys Bridge activo en puerto 3000
- [ ] Git clone/workspace actualizado

---

## 📦 Instalación (5 minutos)

### Paso 1: Instalar Dependencias
```bash
cd bot_empanadas
pip install -r requirements.txt
```
- [ ] reportlab instalado correctamente
- [ ] Verificar: `python -c "import reportlab"`

### Paso 2: Crear Carpeta de Documentos
```bash
mkdir -p documents
```
- [ ] Carpeta `/documents` existe
- [ ] Permisos de escritura verificados

### Paso 3: Configurar Archivo de Configuración

**En `app.py`:**
```python
app.config["PUBLIC_BASE_URL"] = "http://localhost:5000"
```
- [ ] URL configurada correctamente
- [ ] Coincide con Baileys Bridge config

**En `pdf_service.py`:**
```python
empresa_nombre="QUE CHIMBA"
empresa_rfc="QUI123456ABC"  # CAMBIAR A RFC REAL
```
- [ ] Empresa actualizada
- [ ] RFC actual (no ejemplo)

---

## ✅ Verificación: Archivos Modificados

### `requirements.txt`
- [ ] Contiene `reportlab>=3.6,<4.0`
- [ ] Versión correcta especificada

### `pdf_service.py`
- [ ] Archivo existe en `services/`
- [ ] Función `generar_pdf_factura()` presente
- [ ] Importa reportlab correctamente

### `whatsapp_service.py`
- [ ] Función `send_document_whatsapp()` agregada
- [ ] Importa requests
- [ ] Manejo de errores presente

### `report_routes.py`
- [ ] Función `api_admin_invoice_delivery()` actualizada
- [ ] Genera PDFs automáticamente
- [ ] Envía por WhatsApp si status="entregada"
- [ ] Endpoint `/documents/<filename>` agregado
- [ ] Imports correctos (pdf_service, Path)

### `db.py`
- [ ] `obtener_pedido_por_id()` existe
- [ ] `obtener_cliente_por_id()` existe
- [ ] `obtener_datos_fiscales_por_id()` existe
- [ ] `obtener_items_pedido()` existe
- [ ] `registrar_auditoria_factura()` funciona

---

## 🧪 Testing

### Test 1: Sintaxis Python
```bash
python -m py_compile bot_empanadas/db.py
python -m py_compile bot_empanadas/routes/report_routes.py
python -m py_compile bot_empanadas/services/whatsapp_service.py
```
- [ ] db.py compila sin errores
- [ ] report_routes.py compila sin errores
- [ ] whatsapp_service.py compila sin errores

### Test 2: Imports
```bash
python -c "from bot_empanadas.services.pdf_service import generar_pdf_factura"
python -c "from bot_empanadas.services.whatsapp_service import send_document_whatsapp"
python -c "from bot_empanadas import db; print(hasattr(db, 'obtener_pedido_por_id'))"
```
- [ ] PDF service importa OK
- [ ] WhatsApp service importa OK
- [ ] DB functions existen

### Test 3: Suite de Tests
```bash
python test_integracion_pdf_whatsapp.py
```
- [ ] Todos los tests pasan
- [ ] No hay excepciones

### Test 4: Generar PDF Test
```python
from bot_empanadas.services.pdf_service import generar_pdf_factura

resultado = generar_pdf_factura(
    pedido_id=999,
    folio_factura="TEST-999",
    datos_cliente={"nombre": "Test", "apellidos": "User"},
    datos_fiscales={"rfc": "TEST1234567"},
    items_pedido=[{"producto_nombre": "Test", "cantidad": 1, "precio_unitario": 1000, "subtotal": 1000}],
    total=1000
)

print(resultado)
```
- [ ] PDF generado sin errores
- [ ] Archivo existe en disco
- [ ] Contiene datos correctamente

---

## 🔌 Integración con Sistema Existente

### Flask App
- [ ] app.py carga sin errores
- [ ] routes se registran correctamente
- [ ] No hay conflictos de blueprints

### Base de Datos
- [ ] Tabla `facturas_operativas` existe
- [ ] Tabla `auditoria_facturas` existe
- [ ] Tabla `datos_fiscales_clientes` existe

### Baileys Bridge
- [ ] Bridge activo: `curl http://localhost:3000/health`
- [ ] Token de API configurado
- [ ] Puede enviar mensajes de texto

---

## 🚀 Funcionalidad Core

### API: POST /api/admin/finanzas/factura
```bash
curl -X POST http://localhost:5000/api/admin/finanzas/factura \
  -H "Content-Type: application/json" \
  -d '{"pedido_id": 1, "folio_factura": "TEST-001", "status": "emitida"}'
```
- [ ] Respuesta 200 OK
- [ ] JSON válido en respuesta
- [ ] Campo "pdf" incluido
- [ ] PDF generado en carpeta /documents

### API: POST con status="entregada"
```bash
curl -X POST http://localhost:5000/api/admin/finanzas/factura \
  -H "Content-Type: application/json" \
  -d '{"pedido_id": 1, "folio_factura": "TEST-001", "status": "entregada"}'
```
- [ ] Respuesta 200 OK
- [ ] Campo "notificacion_cliente" incluido
- [ ] "pdf_enviado": true
- [ ] Cliente recibe WhatsApp (si número válido)

### API: GET /api/admin/finanzas/factura/historial
```bash
curl "http://localhost:5000/api/admin/finanzas/factura/historial?pedido_id=1"
```
- [ ] Respuesta 200 OK
- [ ] Array de eventos en "eventos"
- [ ] Eventos ordenados por fecha
- [ ] Cada evento tiene tipo, usuario, detalles

### Servicio: GET /documents/<filename>
```bash
curl http://localhost:5000/documents/TEST-001.pdf > test.pdf
file test.pdf  # Debe ser PDF
```
- [ ] Respuesta 200 OK
- [ ] Content-Type: application/pdf
- [ ] Archivo válido
- [ ] Requiere autenticación

---

## 🔐 Seguridad

### Autenticación
- [ ] /documents/<filename> requiere login
- [ ] Solo admins pueden acceder
- [ ] Tokens de sesión validados

### Validación
- [ ] No hay path traversal en filenames
- [ ] No se sirven archivos fuera de /documents
- [ ] Filenames sanitizados

### Auditoría
- [ ] Cada operación registrada
- [ ] IP origen capturada
- [ ] Usuario admin registrado
- [ ] Timestamp en cada evento

---

## 📊 Monitoreo Post-Implementación

### Logs
- [ ] No hay errores en stderr
- [ ] Logs de acceso válidos
- [ ] Debug messages informativos

### Base de Datos
- [ ] Tabla `auditoria_facturas` tiene registros
- [ ] Tabla `facturas_operativas` se actualiza
- [ ] Índices funcionando

### Rendimiento
- [ ] PDF se genera en < 2s
- [ ] API responde en < 1s
- [ ] No hay memory leaks
- [ ] Conexiones DB se cierran correctamente

---

## 🎯 Validación Final

### Escenario Completo
```
1. Pedido en BD con cliente y datos fiscales
2. Admin emite factura (status=emitida)
   ✓ PDF generado
   ✓ Auditoría registrada
3. Admin marca entregada (status=entregada)
   ✓ PDF enviado por WhatsApp
   ✓ Cliente recibe mensaje
   ✓ Auditoría registrada
4. Verificar historial
   ✓ Todos los eventos presentes
   ✓ Datos completos
```

### Casos de Error
- [ ] Pedido_id inválido → 400
- [ ] Folio_factura ausente → 400
- [ ] Status inválido → 400
- [ ] Pedido no existe → 404 (graceful)
- [ ] WhatsApp Bridge down → error logeado
- [ ] PDF generation error → error en respuesta

---

## 📚 Documentación Presente

- [ ] `INTEGRACION_PDF_WHATSAPP_2026-04-20.md` exists
- [ ] `GUIA_RAPIDA_PDF_WHATSAPP.md` exists
- [ ] `RESUMEN_EJECUTIVO_PDF_WHATSAPP.md` exists
- [ ] Docstrings en todas las funciones nuevas
- [ ] Comentarios en código complejo

---

## ✨ Características Opcionales

- [ ] QR en PDF (future)
- [ ] Reporte de facturas (future)
- [ ] Re-envío manual (future)
- [ ] Factura Electrónica SAT (future)

---

## 🏁 Go/No-Go para Producción

### Must-Haves ✅
- [ ] Todos los tests pasan
- [ ] PDF se genera correctamente
- [ ] WhatsApp delivery funciona
- [ ] Auditoría completa

### Should-Haves ✅
- [ ] Documentación completa
- [ ] Error handling robusto
- [ ] Logging detallado

### Nice-to-Haves
- [ ] Métricas de rendimiento
- [ ] Dashboard de facturas
- [ ] Descarga UI

---

## 🚀 Decisión Final

**¿PROCEDER A PRODUCCIÓN?**

- [ ] Sí, todo está listo
- [ ] No, requiere ajustes
- [ ] Sí, con monitoreo cercano

**Observaciones:**
```
[Espacio para notas]
```

---

**Checklist Completado:** _______________  
**Fecha:** __________________  
**Responsable:** __________________  
**Aprobado por:** __________________

---

## 📞 Contacto de Soporte

Si algo no funciona:

1. **Verificar logs:**
   ```bash
   tail -f logs/app.log
   tail -f logs/audit.log
   ```

2. **Revisar documentación:**
   - `GUIA_RAPIDA_PDF_WHATSAPP.md` - Troubleshooting
   - `INTEGRACION_PDF_WHATSAPP_2026-04-20.md` - Detalles técnicos

3. **Ejecutar tests:**
   ```bash
   python test_integracion_pdf_whatsapp.py
   ```

4. **Verificar configuración:**
   - URL pública correcta?
   - Bridge activo?
   - Tabla de base de datos OK?

---

**Última actualización:** 2026-04-20  
**Versión del checklist:** 1.0
