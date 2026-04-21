# AUDITORÍA SISTEMA DE FACTURAS
## Que Chimba - 2026-04-20

### EJECUTIVO

El sistema de facturas está **parcialmente funcional** pero **NO LISTO PARA PRODUCCIÓN**. Hay vulnerabilidades, gaps de integración y problemas de encriptación que impiden emisión y entrega real de facturas a clientes.

---

## 1. ESTADO ACTUAL DEL SISTEMA

### 1.1 Componentes Implementados ✅

| Componente | Estado | Detalles |
|-----------|--------|----------|
| **BD - Tabla facturas_operativas** | ✅ Funcional | Almacena folio, estado (emitida/entregada), email_destino, timestamps |
| **BD - Tabla datos_fiscales** | ✅ Funcional | Almacena RFC, razón social, régimen, uso CFDI, email (con encriptación) |
| **Chatbot - Solicitud datos fiscales** | ✅ Funcional | FSM solicita RFC\|RAZON\|REGIMEN\|CFDI\|EMAIL en estado `datos_fiscales` |
| **Validación RFC** | ✅ Funcional | Regex valida formato RFC mexicano con 16 caracteres |
| **Admin Panel - Formulario factura** | ✅ Funcional | Captura pedido_id, folio_factura, status, notas |
| **API /admin/finanzas/factura** | ✅ Funcional | POST registra factura en BD y retorna datos |
| **Encriptación sensible** | ⚠️ Parcial | Funciones `encrypt_sensitive_text/decrypt_sensitive_text` existen pero **hay problemas** |

### 1.2 Problemas Identificados 🔴

#### CRÍTICO: Encriptación de Email No Funciona
**Ubicación:** `db.py` líneas 179-211
```python
# Los campos se encriptan pero en registrar_factura_operativa:
COALESCE(decrypt_sensitive_text(df.email_enc), df.email, '')
# Esto FALLA porque:
# 1. email_enc es BYTEA pero decrypt() espera el formato correcto
# 2. No hay fallback a email_enc si email es NULL
# 3. El decrypt() puede retornar NULL si hay problemas
```

**Impacto:** El email no se recupera correctamente → notificación al cliente falla.

#### CRÍTICO: Sin Envío Real de Factura PDF
**Ubicación:** Ningún lugar en el código
- ✅ Se registra folio en BD
- ✅ Se notifica por WhatsApp que factura está lista
- ❌ **NO se genera PDF de factura**
- ❌ **NO se envía PDF por email**
- ❌ **Cliente NO recibe documento fiscal real**

**Impacto:** Sistema es incompleto - solo guarda metadata, no entrega producto.

#### ALTO: Validación de Email Incompleta
**Ubicación:** `bot.py` línea 1930
```python
if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
    return None  # Rechazo silencioso
```
- Regex es básico, no valida dominios válidos
- No hay normalización de caso (acepta MaIxEd case)
- No hay comprobación de deliverability

#### ALTO: Falta de Logging de Auditoría
**Ubicación:** Ningún lugar
- No se registra quién emitió cada factura
- No se registra timestamp exacto de emisión
- No hay trazabilidad de cambios de estado
- No hay registro de intentos fallidos de notificación

#### MEDIO: Falta de Manejo de Errores Robusto
**Ubicación:** `report_routes.py` línea 413-433
```python
if status == "entregada" and callable(send_text_whatsapp):
    # Si send_text_whatsapp falla, se registra error
    # Pero NO reintentar
    # Pero NO notificar al admin
    # Pero NO guardar en cola para retry
```

#### MEDIO: Sin Validación de Pedido Completado
**Ubicación:** `db.py` línea 4211
```python
# Al registrar factura no se verifica si:
# - Pedido está realmente entregado
# - Pago fue confirmado
# - Cliente recibió el pedido
```

---

## 2. FLUJO ACTUAL vs ESPERADO

### 2.1 Flujo Actual (Broken)
```
Cliente envía datos fiscales
    ↓
Chatbot valida y guarda en BD
    ↓
Admin captura folio y marca "emitida"
    ↓
Factura se registra en facturas_operativas
    ↓
Admin marca "entregada"
    ↓
WhatsApp notifica cliente: "Tu factura está lista"
    ↓
❌ Cliente NO recibe PDF
❌ No hay confirmación de entrega
❌ No hay trazabilidad fiscal real
```

### 2.2 Flujo Esperado (Production-Ready)
```
Cliente envía datos fiscales RFC|RAZON|REGIMEN|CFDI|EMAIL
    ↓
Chatbot valida RFC, email, guarda en BD con encriptación
    ↓
Pedido se confirma y paga
    ↓
Delivery team confirma entrega física
    ↓
Admin o sistema automático:
  • Genera PDF con datos de factura
  • Valida datos fiscales completos
  • Emite folio único y secuencial
  • Guarda en BLOB o archivo seguro
    ↓
Sistema envía PDF por:
  • Email al cliente
  • WhatsApp como documento
    ↓
Registra en facturas_operativas:
  • folio_factura
  • estado = 'emitida'
  • email_destino
  • timestamp exacto
    ↓
Cliente marca como "entregada"
    ↓
Log de auditoría completo para SAT/validación
```

---

## 3. PROBLEMAS ESPECÍFICOS POR MÓDULO

### 3.1 Bot (bot.py)

#### ✅ Validación RFC - Correcta
```python
# Línea 1927
re.match(r"^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$", rfc)
```
Valida:
- 3-4 letras (A-Z, &, Ñ)
- 6 dígitos
- 3 caracteres alfanuméricos
✅ Correcto para RFC mexicano

#### ⚠️ Validación Email - Incompleta
```python
# Línea 1930
re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email)
```
Problemas:
- Permite emails inválidos: "a@b.c" (aceptado pero incorrecto)
- Permite dominios sin TLD válido
- No normaliza a lowercase

**Corrección necesaria:**
```python
import email_validator

def _validar_email_produccion(email_str):
    try:
        valid = email_validator.validate_email(email_str, check_deliverability=False)
        return valid.normalized
    except:
        return None
```

#### ❌ Falta: Validación de Datos Completos
Cuando cliente da datos_fiscales, NO se valida:
- Que cliente haya completado el pedido
- Que dirección sea válida si es domicilio
- Que tenga al menos un método de pago registrado

#### ❌ Falta: Almacenamiento de Referencia Factura
Una vez datos_fiscales se validan, no hay:
- `datos_temp["datos_fiscales_id"]` para tracking
- Linking automático al pedido
- Persistencia en sesión para recall

### 3.2 Database (db.py)

#### ✅ Tabla facturas_operativas - Bien diseñada
```sql
CREATE TABLE facturas_operativas (
    factura_op_id BIGSERIAL PRIMARY KEY,
    pedido_id BIGINT NOT NULL REFERENCES pedidos(pedido_id),
    datos_fiscales_id BIGINT,
    folio_factura VARCHAR(80) NOT NULL,
    estado VARCHAR(20) DEFAULT 'emitida',
    email_destino VARCHAR(255),
    emitida_en TIMESTAMP NOT NULL DEFAULT NOW(),
    entregada_en TIMESTAMP
)
```
Schema es correcto, indexes están bien.

#### ❌ Falta: Columna para URL/Blob de PDF
No hay lugar para almacenar:
- Path a PDF
- BLOB del PDF
- URL firmada para descargar
- Hash/signature del documento

**Necesario:**
```sql
ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS
  pdf_ruta VARCHAR(255),
  pdf_hash VARCHAR(64),
  pdf_tamano_bytes BIGINT,
  disponible_hasta TIMESTAMP;
```

#### ⚠️ Encriptación de Email - Implementación Confusa
```python
# Línea 232: Crear columna email_enc
ALTER TABLE datos_fiscales ADD COLUMN IF NOT EXISTS email_enc BYTEA

# Línea 270: Encriptar email
email_enc = COALESCE(email_enc, encrypt_sensitive_text(email))

# Línea 4219: Recuperar email (PROBLEMA)
COALESCE(decrypt_sensitive_text(df.email_enc), df.email, '')
```

**Problemas:**
1. `decrypt_sensitive_text(BYTEA)` requiere conversión correcta
2. Si `email_enc` existe pero decrypt falla, retorna ''
3. No hay columna `email_enc` en todos los registros históricos
4. Fallback a `df.email` pero ese campo debería estar NULL si encriptado

**Corrección necesaria:** Revisar funciones de cripto en PostgreSQL

#### ✅ Función registrar_factura_operativa - Lógica correcta
Pero le falta:
- Generación automática de folio secuencial
- Validación de pedido completado
- Almacenamiento de PDF
- Log de auditoría

### 3.3 API Routes (report_routes.py)

#### ✅ POST /api/admin/finanzas/factura - Básicamente correcto
```python
def api_admin_invoice_delivery():
    # Registra factura en BD ✅
    # Envía notificación WhatsApp ✅ (si status == 'entregada')
```

#### ⚠️ Pero le falta:
1. Validación de permisos más estrictos (solo admin)
2. Generación de PDF antes de marcar "emitida"
3. Envío de PDF por email
4. Retry si notificación falla
5. Log completo de auditoría
6. Validación que pedido_id existe y es válido
7. Check de duplicados (mismo pedido con 2 folios)

### 3.4 Admin UI (admin.html)

#### ✅ Formulario de captura - Correcto
```html
<input id="f-fact-pedido" type="number" min="1" />
<input id="f-fact-folio" placeholder="FAC-20260414-001" />
<select id="f-fact-status">
  <option value="emitida">Emitida</option>
  <option value="entregada">Entregada</option>
</select>
<input id="f-fact-notas" placeholder="Correo o detalle" />
```

#### ⚠️ Pero le falta:
1. Preview del PDF antes de confirmar
2. Validación de folio no duplicado
3. Mostrar datos fiscales del cliente
4. Confirmación de que email fue enviado
5. Link para descargar PDF
6. Historial de cambios de estado

---

## 4. CHECKLIST DE PRODUCCIÓN

### 4.1 Seguridad 🔒
- [ ] Encriptación de emails en tránsito y almacenamiento
- [ ] Validación de RFC contra SAT (CURP API)
- [ ] Verificación de email para evitar phishing
- [ ] Rate limiting en API de facturas
- [ ] Logs de auditoría inmutables (append-only)
- [ ] Firmas digitales en PDFs
- [ ] Cumplimiento RGPD (datos sensibles)

### 4.2 Funcionalidad 📋
- [ ] Generación de PDF con logo y datos correctos
- [ ] Folio secuencial y único por año/mes
- [ ] Envío por email con CC/BCC
- [ ] Envío por WhatsApp (documento o link)
- [ ] Retry automático si falla envío
- [ ] Queue/cola para facturas pendientes
- [ ] Download link con token seguro
- [ ] Reporte de facturas emitidas vs entregadas

### 4.3 Auditoría 📊
- [ ] Log de cada emisión (quién, cuándo, qué)
- [ ] Log de cada notificación (éxito/fallo)
- [ ] Trazabilidad completa pedido → factura
- [ ] Reporte SAT-compatible
- [ ] Reconciliación diaria
- [ ] Alertas de anomalías

### 4.4 Disponibilidad ⚙️
- [ ] Respaldo de PDFs (local + cloud)
- [ ] Reanudación de envíos fallidos
- [ ] Sincronización con SAT
- [ ] Rollback de cambios
- [ ] Estadísticas en tiempo real

---

## 5. PLAN DE CORRECCIÓN (PRIORITY ORDER)

### FASE 1: CRÍTICO (This Week)
1. ✅ Crear tablas faltantes con PDF storage
2. ✅ Corregir encriptación de email
3. ✅ Implementar validación de email mejorada
4. ✅ Agregar logging de auditoría básico
5. ✅ Implementar generación de PDF

### FASE 2: ALTO (Next Week)
1. Envío de PDF por email
2. Envío de PDF por WhatsApp
3. Retry automático
4. Folio secuencial validado
5. UI mejorada con preview

### FASE 3: MEDIO (2 Weeks)
1. Sincronización con SAT
2. Reportes complejos
3. Validación CURP
4. Rate limiting
5. Cloud backup

---

## 6. IMPACTO EN PRODUCCIÓN

### 🔴 BLOQUEADORES
1. **No se envían PDFs** → Clientes no reciben facturas reales
2. **Email no se encripta/desencripta correctamente** → Datos sensibles en riesgo
3. **Sin logging de auditoría** → No hay cumplimiento fiscal
4. **Sin validaciones de pedido completado** → Facturas fantasma

### 🟡 RIESGOS ALTOS
1. Duplicado de folios (sin secuencia)
2. Pérdida de PDFs (sin backup)
3. No hay retry si fallan notificaciones
4. Sin trazabilidad de cambios

### 🟢 MEJORAS NECESARIAS
1. UI mejorada
2. Reportes más ricos
3. Integración SAT
4. Validación de datos completos

---

## 7. RECOMENDACIONES INMEDIATAS

### 7.1 Para Producción HOY
```
STOP: No activar sistema de facturas en producción hasta que:
1. ✅ PDFs se generen y almacenen
2. ✅ Email se valide y encripte correctamente
3. ✅ Logging de auditoría está en lugar
4. ✅ Tests de integración pasen
5. ✅ Manual de operación esté listo
```

### 7.2 Workaround Temporal
Mientras se corrige:
- Admin registra factura manualmente en Excel/Google Sheets
- PDF se genera manualmente (herramienta externa)
- PDF se envía manualmente por email
- Registrar folio en sistema para tracking

---

## 8. CONTACTO Y ESCALACIONES

Para cambios de facturación:
- Requiere revisión de auditoría_negocio
- Requiere registro en log_notificaciones
- Requiere aprobación de admin
- Requiere test de integración

