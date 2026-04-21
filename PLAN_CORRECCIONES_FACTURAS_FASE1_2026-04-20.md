# PLAN DE CORRECCIONES DEL SISTEMA DE FACTURAS
## Implementación Fase 1 (2026-04-20)

### ✅ COMPLETADO EN ESTA SESIÓN

#### 1. Validación Mejorada de Email
**Archivo:** `bot_empanadas/bot.py` líneas 1914-1946
- ✅ Nueva función `_validar_email_produccion()` con validación robusta
- ✅ Rechaza emails sin @, con múltiples @, sin TLD
- ✅ Normaliza a lowercase
- ✅ Valida longitud según RFC 5321

#### 2. Validación Mejorada de Datos Fiscales
**Archivo:** `bot_empanadas/bot.py` líneas 1949-2020
- ✅ Nueva función `_parsear_factura()` mejorada
- ✅ Valida regímenes fiscales contra códigos SAT reales
- ✅ Valida usos CFDI correctos (G01-G03, I01-I07, D01-D10)
- ✅ Logging detallado con mascara de datos sensibles
- ✅ Mensajes de error descriptivos

#### 3. Auditoría de Facturas
**Archivo:** `bot_empanadas/db.py` líneas 4268-4380
- ✅ Nueva tabla `auditoria_facturas` con eventos inmutables
- ✅ Nueva función `registrar_auditoria_factura()`
- ✅ Nueva función `obtener_historial_factura()`
- ✅ Índices para consultas rápidas por pedido y evento

#### 4. Logging en Guardado de Datos Fiscales
**Archivo:** `bot_empanadas/bot.py` líneas 1852-1898
- ✅ Mejorada función `_guardar_datos_fiscales_en_db()`
- ✅ Registra auditoría de éxito y fallos
- ✅ Mascara RFC y otros datos sensibles en logs
- ✅ Alertas detalladas de problemas

#### 5. API Mejorada de Facturas
**Archivo:** `bot_empanadas/routes/report_routes.py` líneas 386-564
- ✅ Mejorada función `api_admin_invoice_delivery()`
  - Validación completa de parámetros
  - Validación de longitud y formato de folio
  - Logging de cada paso
  - Auditoría de éxito y fallos
  - Notificación mejorada al cliente
  
- ✅ Nueva función `api_admin_invoice_audit_history()`
  - GET endpoint para historial completo
  - Retorna todos los eventos en orden cronológico

#### 6. Nuevas Rutas API
**Archivo:** `bot_empanadas/routes/report_routes.py` líneas 565-569
- ✅ POST `/api/admin/finanzas/factura` mejorado
- ✅ GET `/api/admin/finanzas/factura/historial` nuevo

---

## PRÓXIMAS MEJORAS (FASE 2)

### CRÍTICO: Envío de Facturas Reales

**❌ TODO:** Implementar generación de PDF

```python
# En db.py agregar:
def generar_pdf_factura(factura_op_id, datos_pedido, datos_fiscales):
    """
    Genera PDF de factura con:
    - Logo de empresa
    - RFC y razón social
    - Detalles del pedido
    - Firma digital/folio SAT
    
    Retorna: ruta del PDF generado
    """
    # Usar reportlab o weasyprint
    pass
```

**❌ TODO:** Implementar envío por Email

```python
# En services/email_service.py agregar:
def enviar_factura_por_email(email_destino, pdf_ruta, folio_factura):
    """
    Envía PDF de factura por email con:
    - Asunto profesional
    - Cuerpo personalizado
    - PDF como attachment
    - CC a admin
    - Retry automático
    """
    pass
```

**❌ TODO:** Almacenar URLs de PDFs

```sql
-- Agregar columnas a facturas_operativas:
ALTER TABLE facturas_operativas ADD COLUMN IF NOT EXISTS
  pdf_ruta VARCHAR(255),           -- Path local o cloud
  pdf_url_temporal VARCHAR(500),   -- URL con token
  pdf_url_expira TIMESTAMP,        -- Cuándo expira link
  pdf_hash VARCHAR(64);             -- SHA256 del PDF
```

### ALTO: Validación de Pedido Completado

**❌ TODO:** Agregar checks antes de emitir factura

```python
def puede_emitirse_factura(pedido_id):
    """
    Verifica que:
    - Pedido existe
    - Pedido fue entregado
    - Pago fue confirmado
    - Cliente tiene datos fiscales
    - Aún no existe factura para este pedido
    """
    pass
```

### ALTO: Folio Secuencial Validado

**❌ TODO:** Generar folios automáticos

```python
def generar_folio_secuencial(prefijo="FAC", año=None, mes=None):
    """
    Genera folio secuencial:
    - FAC-2026-04-000001
    - FAC-2026-04-000002
    - Valida unicidad
    - Evita gaps
    """
    pass
```

### MEDIO: Sincronización con SAT

**❌ TODO:** Validación con SAT

```python
def validar_rfc_en_sat(rfc):
    """Verifica RFC contra padrón SAT"""
    pass

def validar_regimen_en_sat(rfc, regimen):
    """Verifica que RFC tenga ese régimen"""
    pass
```

---

## INSTRUCCIONES DE USO EN PRODUCCIÓN

### 1. Flujo Completo de Factura

```
1. Cliente pide factura → Chatbot solicita datos
   ↓
2. Cliente envía: RFC|RAZONSOCIAL|REGIMEN|CFDI|EMAIL
   ↓
3. Bot valida con _parsear_factura()
   ✅ Si válido:
      - Guarda en datos_fiscales con encriptación
      - Registra auditoría "datos_guardados"
      - Confirma al cliente
   ❌ Si inválido:
      - Registra auditoría "validacion_fallida"
      - Pide repetir
   ↓
4. Pedido se confirma y entrega
   ↓
5. Admin ingresa a panel:
   - Captura pedido_id
   - Captura folio_factura (p.ej. FAC-2026-04-001)
   - Selecciona status: "emitida" o "entregada"
   - (Opcional) notas
   ↓
6. Sistema registra:
   - facturas_operativas (folio, status)
   - auditoria_facturas (evento, actor, timestamp)
   - Notifica cliente por WhatsApp
   ↓
7. Admin marca como "entregada"
   - PDF debería estar listo
   - Email debería estar enviado (TODO)
   - Cliente recibe confirmación por WhatsApp
```

### 2. Consultar Historial de Auditoría

```bash
curl -X GET "http://localhost:5000/api/admin/finanzas/factura/historial?pedido_id=123" \
  -H "Authorization: Bearer <token>"
```

Respuesta:
```json
{
  "pedido_id": 123,
  "eventos": [
    {
      "auditoria_id": 1,
      "evento_tipo": "datos_guardados",
      "actor_username": "bot",
      "actor_rol": "bot",
      "detalles": {
        "cliente_id": 45,
        "rfc_partial": "ABC1****XYZ",
        "email_present": true
      },
      "creado_en": "2026-04-20T14:30:00Z"
    },
    {
      "auditoria_id": 2,
      "evento_tipo": "factura_emitida",
      "actor_username": "admin_user",
      "actor_rol": "admin",
      "detalles": {
        "folio": "FAC-****",
        "notas_presentes": false
      },
      "creado_en": "2026-04-20T14:35:00Z"
    },
    {
      "auditoria_id": 3,
      "evento_tipo": "notificacion_whatsapp_enviada",
      "actor_username": "admin_user",
      "actor_rol": "admin",
      "detalles": {
        "destino": "+5216144123456"
      },
      "creado_en": "2026-04-20T14:35:05Z"
    }
  ],
  "total": 3
}
```

### 3. Registrar Factura (Admin Panel)

```javascript
// Desde formulario admin.html
const payload = {
  pedido_id: 123,
  folio_factura: "FAC-2026-04-001",
  status: "emitida",  // o "entregada"
  notas: "Enviado por correo"
};

const response = await fetch("/api/admin/finanzas/factura", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token}`
  },
  body: JSON.stringify(payload)
});

const result = await response.json();
console.log(result);
// {
//   "factura_op_id": 456,
//   "pedido_id": 123,
//   "folio_factura": "FAC-2026-04-001",
//   "estado": "emitida",
//   "notificacion_cliente": {
//     "enviado": true,
//     "motivo": null,
//     "destino": "+5216144123456"
//   }
// }
```

---

## VALIDACIONES ACTIVAS

### Validación de RFC
```
Formato: AAAA123456XYZ o AAA123456XYZ
- 3-4 letras (A-Z, &, Ñ)
- 6 dígitos (0-9)
- 3 caracteres alfanuméricos (A-Z, 0-9)

Ejemplo válido: ABC123456T12, &MI123456XYZ

Rechazados:
- abc123456t12 (lowercase)
- ABC 123456 T12 (espacios no permitidos)
- ABC12345678 (muy corto)
```

### Validación de Email
```
Implementación mejorada:
- Patrón: [a-z0-9._%-]+@[a-z0-9.-]+\.[a-z]{2,}
- Solo 1 @ permitido
- Mínimo 4 caracteres
- Máximo 255 caracteres
- No más de 64 caracteres antes de @
- No termina con punto
- No contiene puntos dobles

Ejemplos válidos:
- cliente@empresa.com
- maria.lopez@miempresa.com.mx
- contacto_ventas@empresa.co

Rechazados:
- cliente @empresa.com (espacio)
- cliente@@empresa.com (doble @)
- cliente.@empresa.com (. antes de @)
- @empresa.com (sin usuario)
```

### Validación de Régimen Fiscal
```
Códigos válidos (SAT 2024):
- 601: General de Ley Personas Morales
- 603: Personas Morales con Fines no Lucrativos
- 605: Sueldos y Salarios
- 606: Arrendamiento
- 607: Otros Ingresos
- 608: Dividendos
- 610: Ingresos por Intereses
- 614: Ganancias de Capital
- 616: Sin Obligación de llevar Contabilidad
- 620: Sociedades Cooperativas
- 621-629: Gobierno Federal/Entidades
- 701: Personas Físicas
- 702: Actividades Empresariales

Si proporciona otro, se acepta pero SAT lo validará.
```

### Validación de Uso CFDI
```
Códigos válidos:
G01, G02, G03: Gobierno
I01-I07: Ingresos
D01-D10: Deducciones/Gastos

Ejemplo: G01 (compra de bienes)
```

---

## CHECKLIST PRE-PRODUCCIÓN

### Seguridad
- [ ] Encriptación de email en BD funciona correctamente
- [ ] Logs no exponen datos fiscales completos
- [ ] Validaciones de input evitan inyección SQL
- [ ] Rate limiting en API de facturas
- [ ] HTTPS configurado

### Funcionalidad
- [ ] Datos fiscales se guardan correctamente
- [ ] Auditoría registra todos los eventos
- [ ] Notificaciones WhatsApp funcionan
- [ ] Historial de auditoría es accesible
- [ ] PDFs se generan (fase 2)
- [ ] Emails se envían (fase 2)

### Disponibilidad
- [ ] BD y respaldos están en lugar
- [ ] Índices están optimizados
- [ ] Logs se guardan en archivo
- [ ] Alertas están configuradas

### Cumplimiento
- [ ] RGPD: Datos sensibles encriptados
- [ ] SAT: Formato de datos cumple normas
- [ ] Auditoría: Historial completo
- [ ] Trazabilidad: Cada cambio registrado

---

## CONTACTO Y ESCALACIONES

Para problemas:
1. Revisar `auditoria_facturas` para ver dónde falló
2. Revisar logs del sistema en `/logs/`
3. Probar función manualmente en Python

Para cambios:
- Requiere code review
- Requiere test de integración
- Requiere actualización de documentación
- Requiere aprobación de admin

