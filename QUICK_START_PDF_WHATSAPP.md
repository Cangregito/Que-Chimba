# ⚡ QUICK START: 3 Pasos para Tener Facturas con WhatsApp

## 1️⃣ Instalar (1 minuto)
```bash
cd bot_empanadas
pip install reportlab
```

✅ Listo.

---

## 2️⃣ Configurar (2 minutos)
Abre `app.py` y verifica:
```python
app.config["PUBLIC_BASE_URL"] = "http://localhost:5000"
# O si estás en producción:
app.config["PUBLIC_BASE_URL"] = "https://tudominio.com"
```

✅ Listo.

---

## 3️⃣ Usar (1 minuto)

### Generar factura
```bash
curl -X POST http://localhost:5000/api/admin/finanzas/factura \
  -H "Content-Type: application/json" \
  -d '{
    "pedido_id": 1,
    "folio_factura": "FAC-001",
    "status": "emitida"
  }'
```

✅ PDF generado en `/documents/FAC-001.pdf`

### Enviar por WhatsApp
```bash
curl -X POST http://localhost:5000/api/admin/finanzas/factura \
  -H "Content-Type: application/json" \
  -d '{
    "pedido_id": 1,
    "folio_factura": "FAC-001",
    "status": "entregada"
  }'
```

✅ Cliente recibe PDF en WhatsApp

---

## 🧪 Verificar que funciona
```bash
python test_integracion_pdf_whatsapp.py
```

Debe mostrar:
```
✅ PASS - Imports/Dependencies
✅ PASS - requirements.txt
✅ PASS - DB Functions
✅ PASS - WhatsApp Function
✅ PASS - PDF Generation
```

---

## 📖 Si algo no funciona
Lee: `GUIA_RAPIDA_PDF_WHATSAPP.md`

---

## 🎉 ¡Listo!
Tu sistema de facturas con WhatsApp está funcionando.

**Siguiente paso:** Leer `INDICE_PDF_WHATSAPP.md` para más detalles.
