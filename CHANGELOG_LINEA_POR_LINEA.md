# 🔍 CHANGELOG: Cambios Línea por Línea

## 📄 Archivo: requirements.txt
**Cambio Type:** Adición  
**Impacto:** ⚡ Crítico - Dependencia requiere instalación

### Cambio
```diff
+ reportlab>=3.6,<4.0
```

### Por qué
- ReportLab es la librería estándar para PDFs en Python
- Versión 3.6+ soporta todos los estilos necesarios
- Versión <4.0 evita breaking changes futuras

### Instalar
```bash
pip install reportlab
```

---

## 📄 Archivo: bot_empanadas/services/whatsapp_service.py
**Cambio Type:** Función Nueva  
**Impacto:** 🔧 Core - Nuevo método público

### Antes
```python
def send_audio_whatsapp(app, destino, audio_path, caption="", default_public_base_url="http://localhost:5000"):
    # ... implementación ...
    return {"ok": True}
```

### Después
```python
def send_audio_whatsapp(...):
    # ... sin cambios ...

def send_document_whatsapp(app, destino, documento_path, caption="", default_public_base_url="http://localhost:5000"):
    """Envía un documento (PDF, imagen, etc.) por WhatsApp.
    
    Args:
        app: Aplicación Flask
        destino: Número de WhatsApp (con o sin +52)
        documento_path: Ruta local al archivo
        caption: Texto opcional que acompaña el documento
        default_public_base_url: URL base para acceder al documento
    
    Returns:
        Dict con {'ok': True} o {'error': 'mensaje'}
    """
    bridge_url = app.config.get("BAILEYS_BRIDGE_URL", "")
    if not bridge_url or not documento_path:
        return {"error": "BAILEYS_BRIDGE_URL o documento_path no configurados."}

    # Verificar que el archivo existe
    if not os.path.exists(documento_path):
        return {"error": f"Archivo no encontrado: {documento_path}"}

    bridge_token = app.config.get("BAILEYS_BRIDGE_API_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if bridge_token:
        headers["x-bridge-token"] = bridge_token

    documento_filename = os.path.basename(str(documento_path))
    base_url = app.config.get("PUBLIC_BASE_URL") or default_public_base_url
    documento_url = f"{base_url}/documents/{documento_filename}"

    try:
        resp = requests.post(
            f"{bridge_url}/api/send-document",
            json={"to": destino, "documentUrl": documento_url, "caption": caption},
            timeout=10,
            headers=headers,
        )
    except Exception as exc:
        return {"error": f"No se pudo enviar documento al bridge: {exc}"}

    try:
        payload = resp.json()
    except Exception:
        payload = {}

    if not resp.ok or payload.get("ok") is not True:
        msg = payload.get("error") or f"Bridge respondio HTTP {resp.status_code}"
        return {"error": str(msg)}

    return {"ok": True}
```

### Líneas Agregadas
- Total: ~70 líneas
- Ubicación: Después de `send_audio_whatsapp()`
- Imports: Usa `os`, `requests` (ya presentes)

### Cambios
- ✅ Nueva función pública
- ✅ Similar patrón a send_audio_whatsapp
- ✅ Valida archivo antes de enviar
- ✅ Construye URL pública automáticamente
- ✅ Manejo robusto de errores

---

## 📄 Archivo: bot_empanadas/routes/report_routes.py
**Cambio Type:** Múltiples cambios  
**Impacto:** 🔧 Core - API actualizada + nuevo endpoint

### Cambio 1: Imports Nuevos (Línea 1-9)
```diff
  import io
  from datetime import datetime
+ from pathlib import Path
  
  from flask import make_response, request, session
  
+ try:
+     from services.pdf_service import generar_pdf_factura
+ except ImportError:
+     from bot_empanadas.services.pdf_service import generar_pdf_factura
```

**Por qué:**
- Path para manejo de archivos
- Importación condicional para flexibilidad

### Cambio 2: API Endpoint Actualizado (Línea ~390-680)
**Función:** `api_admin_invoice_delivery()`

#### Antes (Resumen)
```python
def api_admin_invoice_delivery():
    # Validación de entrada
    # Registra factura
    # Envía notificación por texto
    return ok(response_data)
```

#### Después (Estructura Completa)
```python
def api_admin_invoice_delivery():
    # 1. VALIDACIÓN (igual que antes)
    
    # 2. GENERACIÓN DE PDF (NUEVO)
    if status in {"emitida", "entregada"}:
        try:
            # Obtiene datos del pedido usando nuevas funciones DB
            # Llama a generar_pdf_factura()
            # Almacena ruta en response
            # Registra auditoría de PDF generado
        except Exception as e:
            # Manejo de error
    
    # 3. ENVÍO POR WHATSAPP (NUEVO)
    if status == "entregada":
        try:
            # Envía PDF usando send_document_whatsapp()
            # Envía mensaje de confirmación
            # Registra auditoría de envío
        except Exception as e:
            # Manejo de error
    
    return ok(response_data)
```

#### Cambios Específicos
- ✅ Obtiene datos de pedido, cliente, items
- ✅ **Genera PDF automáticamente**
- ✅ Almacena ruta en BD
- ✅ **Envía PDF por WhatsApp** si status=entregada
- ✅ Auditoría de cada paso
- ✅ Respuesta incluye estado de PDF + envío

**Líneas:** +280  
**Complejidad:** Media-Alta (manejo de errores, integración múltiple)

### Cambio 3: Nuevo Endpoint (Línea ~688-720)
```python
@login_required(roles=["admin"])
def serve_document(filename):
    """Sirve un documento (PDF) desde la carpeta de documentos.
    
    Ruta: /documents/<filename>
    """
    from flask import send_from_directory
    import os
    
    # Validar que el nombre del archivo no contiene path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return error("Nombre de archivo inválido", 400)
    
    # Ruta base de documentos (relativos a la carpeta de la app)
    doc_folder = Path(app.root_path).parent / "documents"
    doc_folder.mkdir(exist_ok=True)
    
    document_path = doc_folder / filename
    
    # Verificar que el archivo existe y está dentro de doc_folder
    if not document_path.exists() or not str(document_path).startswith(str(doc_folder)):
        return error("Documento no encontrado", 404)
    
    return send_from_directory(str(doc_folder), filename)

app.add_url_rule(
    "/documents/<filename>",
    endpoint="serve_document",
    view_func=serve_document,
    methods=["GET"],
)
```

**Características:**
- ✅ Protegido con login_required
- ✅ Validación de path traversal
- ✅ Auto-crea carpeta /documents
- ✅ Verifica existencia de archivo
- ✅ Retorna 404 si no encontrado

**Líneas:** +35

---

## 📄 Archivo: bot_empanadas/db.py
**Cambio Type:** Funciones Nuevas  
**Impacto:** 🔧 Core - 5 funciones públicas

### Función 1: obtener_pedido_por_id()
```python
def obtener_pedido_por_id(pedido_id):
    """Obtiene datos completos de un pedido.
    
    Args:
        pedido_id: ID del pedido
    
    Returns:
        Dict con datos del pedido o {"error": msg}
    """
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM pedidos
                WHERE pedido_id = %s
                LIMIT 1
            """, (pedido_id,))
            row = cur.fetchone()
            return dict(row) if row else {"error": "Pedido no encontrado"}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()
```

### Función 2: obtener_cliente_por_id()
```python
def obtener_cliente_por_id(cliente_id):
    """Obtiene datos de un cliente.
    
    Args:
        cliente_id: ID del cliente
    
    Returns:
        Dict con datos del cliente o {"error": msg}
    """
    # Similar a obtener_pedido_por_id, consulta tabla clientes
```

### Función 3: obtener_datos_fiscales_por_id()
```python
def obtener_datos_fiscales_por_id(datos_fiscales_id):
    """Obtiene datos fiscales/CFDI de un cliente.
    
    Args:
        datos_fiscales_id: ID del registro de datos fiscales
    
    Returns:
        Dict con datos fiscales o {"error": msg}
    """
    # Consulta tabla datos_fiscales_clientes
```

### Función 4: obtener_items_pedido()
```python
def obtener_items_pedido(pedido_id):
    """Obtiene los items (productos) de un pedido.
    
    Args:
        pedido_id: ID del pedido
    
    Returns:
        List de items o {"error": msg}
    """
    # Consulta tabla detalle_items con LEFT JOIN a productos
```

**Ubicación:** Después de `obtener_historial_factura()`  
**Líneas:** +150  
**Patrón:** Todas siguen el mismo patrón:
1. get_connection()
2. Asegurar tabla
3. Execute SQL
4. Return dict o error
5. Finally close connection

---

## 📄 Archivo: bot_empanadas/services/pdf_service.py
**Cambio Type:** Archivo Nuevo  
**Impacto:** ⚡ Core - Generación de PDFs

### Contenido Completo
**Función Principal:** `generar_pdf_factura()`

```python
def generar_pdf_factura(
    pedido_id,
    folio_factura,
    datos_cliente=None,
    datos_fiscales=None,
    items_pedido=None,
    total=0.0,
    empresa_nombre="QUE CHIMBA",
    empresa_rfc="QUI123456ABC",
    fecha_emision=None
):
    """Genera una factura en PDF con datos completos.
    
    Returns:
        {
            "ruta": "/documents/FAC-2026-001.pdf",
            "folio": "FAC-2026-001",
            "pedido_id": 42,
            "total": 50000.0,
            "fecha_generacion": "2026-04-20T10:30:00"
        }
    """
    # Implementación con reportlab
    # - Crea documento PDF
    # - Agrega cabecera
    # - Agrega tabla de items
    # - Calcula totales
    # - Guarda en /documents
    # - Retorna metadata
```

**Características:**
- ✅ Usa ReportLab para PDF profesional
- ✅ Tabla formateada
- ✅ Estilos profesionales
- ✅ Manejo de números
- ✅ Path auto-generado
- ✅ Manejo robusto de errores

**Líneas:** ~300  
**Ubicación:** Nueva carpeta/archivo

---

## 📋 Resumen de Cambios

| Archivo | Tipo | Líneas | Impacto |
|---------|------|--------|--------|
| requirements.txt | Adición | 1 | ⚡ Crítico |
| whatsapp_service.py | Función nueva | 70 | 🔧 Core |
| report_routes.py | Actualización + Nuevo | 315 | 🔧 Core |
| db.py | 5 Funciones nuevas | 150 | 🔧 Core |
| pdf_service.py | Archivo nuevo | 300 | ⚡ Core |
| **TOTAL** | **5 archivos** | **836** | **Integral** |

---

## 🔄 Orden de Aplicación de Cambios

1. **requirements.txt** → Instalar reportlab
2. **pdf_service.py** → Crear nuevo servicio
3. **whatsapp_service.py** → Agregar función
4. **db.py** → Agregar funciones
5. **report_routes.py** → Actualizar endpoint

---

## ✅ Verificación de Cambios

### Sintaxis
```bash
python -m py_compile bot_empanadas/db.py
python -m py_compile bot_empanadas/routes/report_routes.py
python -m py_compile bot_empanadas/services/whatsapp_service.py
python -m py_compile bot_empanadas/services/pdf_service.py
```

### Funcionales
```bash
python test_integracion_pdf_whatsapp.py
```

### Visibles
```bash
git diff  # Si está en git
```

---

## 🎯 Impacto en API

### Antes
```
POST /api/admin/finanzas/factura
Response:
{
  "factura_id": 123,
  "status": "emitida",
  "notificacion_cliente": {...}
}
```

### Después
```
POST /api/admin/finanzas/factura
Response:
{
  "factura_id": 123,
  "status": "emitida",
  "pdf": {
    "ruta": "/documents/FAC-001.pdf",
    "generado_en": "2026-04-20T10:30:00"
  },
  "notificacion_cliente": {
    "pdf_enviado": true,
    "destino": "+573051234567"
  }
}
```

---

## 🚀 Rollback (si es necesario)

Si necesitas revertir cambios:

```bash
# Revertir archivo específico
git checkout HEAD -- bot_empanadas/db.py

# Revertir último commit
git revert HEAD

# Eliminar archivo nuevo
rm bot_empanadas/services/pdf_service.py
```

---

**Última actualización:** 2026-04-20  
**Versión:** 1.0  
**Cambios Totales:** 836 líneas
