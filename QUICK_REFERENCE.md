# ⚡ QUICK REFERENCE - CIERRE CAJA v2.0

**Imprime esto o mantenlo a mano durante implementación**

---

## 🎯 CHECKLIST DE INTEGRACIÓN (5 MIN)

```
[ ] 1. Abre: bot_empanadas/templates/admin.html

[ ] 2. Busca (Ctrl+F): "Registrar cierre de caja real por turno"

[ ] 3. Selecciona TODA la sección:
      Desde: <article class="flat card"... (línea ~1441)
      Hasta: </article> (incluir cierre)

[ ] 4. Abre: NUEVO_CIERRE_CAJA_INTERFACE_HTML.html

[ ] 5. Copia TODO (Ctrl+A, Ctrl+C)

[ ] 6. Vuelve a admin.html, pega (Ctrl+V)

[ ] 7. Guarda (Ctrl+S)

[ ] 8. Reinicia app (Ctrl+C + python -m bot_empanadas.app)

[ ] 9. Prueba: http://localhost:5000/admin → Finanzas → Cierre Caja

[ ] 10. Verifica: Se ve interfaz nueva ✓
```

---

## 🚨 SI ALGO SALE MAL

| Problema | Solución |
|----------|----------|
| "404 API" | Reinicia app completamente |
| "No se ve UI nueva" | Limpiar caché (Ctrl+Shift+Del) |
| "Error en consola" | Ver INSTRUCCIONES_INTEGRACION_5MIN.md |
| "Errores de Python" | Verificar db_cierre_caja_v2.py existe |
| "Datos no se cargan" | Esperar 5 seg + recargar página |

---

## 📊 TOLERANCIA RÁPIDA

```
Cálculo: MAX(3, vol_eff × 0.005) + MAX(2, vol_dig × 0.003)

Ejemplos:
┌────────────┬──────────────────┬──────────────┐
│ Turno $    │ Composición      │ Tolerancia   │
├────────────┼──────────────────┼──────────────┤
│ $5,000     │ $3,000/$2,000    │ ±$20         │
│ $10,000    │ $7,000/$3,000    │ ±$44         │
│ $15,000    │ $8,000/$7,000    │ ±$61         │
│ $20,000    │ $12,000/$8,000   │ ±$84         │
└────────────┴──────────────────┴──────────────┘
```

---

## 🔄 FLUJO DE USUARIO

```
1. Selecciona turno → 2. Carga datos → 3. Ingresa conteos → 4. Valida
                            ↓
              Pre-llena (caja_inicial,
              eff_sistema, dig_sistema,
              tolerancia)
                            
                      Usuario ingresa:
                      - Efectivo contado
                      - Digital contado
                      - Gastos (3 tipos)
                                    ↓
                            Sistema calcula:
                            - Diferencia
                            - Estado (✓/⚠️/❌)
                            - Dentro tolerancia?
                                    ↓
              ┌─────────────────────────────┐
              │ ¿Está bien?                 │
              ├─────────────────────────────┤
              │ SÍ: [Guardar] ✓             │
              │ NO: [Investigar] o [Editar] │
              └─────────────────────────────┘
```

---

## 📱 CÓDIGOS DE ESTADO

```
VERDE  ✓ CUADRADO
       Diferencia = $0 o muy pequeña
       Dentro de tolerancia
       → Guardar

AMARILLO ⚠️ TOLERABLE
       Diferencia pequeña
       Dentro de tolerancia ±XX
       → Guardar (normal)

ROJO   ❌ FALTANTE/SOBRANTE
       Diferencia significativa
       FUERA de tolerancia
       → Investigar o recontar
```

---

## 🔐 ROLES Y PERMISOS

```
OPERADOR:
├─ Puede crear cierre (registrar)
├─ Puede recontar y editar
└─ NO puede aprobar

GERENTE/ADMIN:
├─ Puede ver todos los cierres
├─ Puede aprobar cierres (draft → approved)
├─ Puede rechazar (draft → rejected)
└─ Puede iniciar investigación
```

---

## 📂 ARCHIVOS MODIFICADOS

```
✅ bot_empanadas/db.py
   - Ampliada tabla (10 campos)
   - Nueva tabla investigaciones
   - Mejores cálculos

✅ bot_empanadas/db_cierre_caja_v2.py (NUEVO)
   - 6 funciones workflow

✅ bot_empanadas/routes/report_routes.py
   - 7 nuevos endpoints

⏳ bot_empanadas/templates/admin.html
   - Reemplazar sección (PENDIENTE)
```

---

## 🔌 ENDPOINTS API

```
GET  /api/admin/finanzas/cierre-caja/prefill
     → {caja_inicial, eff_sistema, dig_sistema, tolerancia}

POST /api/admin/finanzas/cierre-caja/v2
     → {cierre_id, status, workflow_status}

POST /api/admin/finanzas/cierre-caja/aprobar
     → {resultado: aprobado}

POST /api/admin/finanzas/cierre-caja/rechazar
     → {resultado: rechazado, razon}

POST /api/admin/finanzas/cierre-caja/investigacion/iniciar
     → {investigacion_id}

GET  /api/admin/finanzas/cierres/pendientes
     → [{cierre1}, {cierre2}, ...]

GET  /api/admin/finanzas/cierres/resumen
     → {resumen_diario}
```

---

## 🧪 TEST RÁPIDO

```
Datos de prueba:
├─ Turno: Mañana
├─ Fecha: Hoy
├─ Caja inicial: $2,500
├─ Eff. sistema: $8,450
├─ Dig. sistema: $7,200
├─ Eff. contado: $10,950 ← CUADRADO
├─ Dig. contado: $7,200
├─ Gastos insumos: $45
└─ Esperado resultado: CUADRADO ✓

Resultado:
├─ Diferencia: $0
├─ Estado: VERDE
├─ Mensaje: "Cierre cuadrado"
└─ Se guarda exitosamente
```

---

## 📞 DOCUMENTACIÓN RÁPIDA

| Documento | Para |
|-----------|------|
| **RESUMEN_QUE_SE_HIZO.md** | Entender qué se hizo |
| **INSTRUCCIONES_INTEGRACION_5MIN.md** | Cómo integrar paso a paso |
| **CHECKLIST_IMPLEMENTACION_CIERRE_CAJA.md** | Verificar cada paso |
| **GUIA_INTEGRACION_CIERRE_CAJA_V2.md** | Detalles técnicos |
| **RESUMEN_EJECUTIVO_CIERRE_CAJA_V2.md** | Visual y completo |

---

## ⏱️ TIMELINE

```
Tarea                    Tiempo    Acumulado
─────────────────────────────────────────────
1. Integración HTML      5 min     5 min
2. Reinicio app          1 min     6 min
3. Prueba básica         3 min     9 min
4. Capacitación ops      15 min    24 min

TOTAL PARA PRODUCCIÓN: ~25 minutos
```

---

## ✨ VARIABLES IMPORTANTES

```javascript
// Estas funciones YA EXISTEN en admin.html
// El código nuevo las usa:

qs()      → querySelector (buscar elementos)
api()     → Llamadas fetch a API
toast()   → Notificaciones al usuario
mxn()     → Formato moneda
html()    → Actualizar innerHTML
num()     → Parsear números

// El código nuevo AGREGA:
cierreState    → Objeto de estado global
cargarDatos()  → Carga desde API
calcularDiferencias()  → Validación tiempo real
guardarCierre()        → POST a API
```

---

## 🎓 CAPACITACIÓN OPERADORES (RÁPIDO)

```
MOSTRAR ESTO EN 5 MINUTOS:

1. "Van a Finanzas → Cierre de Caja"
   (Les muestras dónde es)

2. "Seleccionan turno → Presionan 'Cargar'"
   (Les muestras que pre-llena automático)

3. "Ingresa lo que contaron y el sistema valida"
   (Les muestras validación en tiempo real)

4. "Si está bien, guardan. Si no, investigan"
   (Les muestras opciones)

5. "¿Preguntas?"

FIN. Prácticos ellos con datos de prueba.
```

---

## 🚀 COMANDO DE INICIO

```bash
# Después de integrar HTML:

cd "C:\Users\jassi\OneDrive - Universidad Tecnologica de Ciudad Juárez\Segundo Cuatri\Administracion de bases de datos\Que chimba"

python -m bot_empanadas.app

# Debería ver:
# * Running on http://127.0.0.1:5000
# 
# Base de datos conectada ✓
# Migraciones ejecutadas ✓
# No hay errores ✓

# Abre navegador:
# http://localhost:5000/admin
```

---

## 📊 MÉTRICAS POST-IMPLEMENTACIÓN

Medir después de 1 semana:

```
Métrica                 Meta        Actual
────────────────────────────────────────────
Tiempo cierre          <5 min       ____
Errores operadores     <5%          ____
Satisfacción ops       8/10         ____
Recapituras            <2%          ____
Problemas reportados   0-2          ____
```

---

## 🎯 PRÓXIMOS PASOS (DESPUÉS DE v2.0)

```
Fase 2 (Semana 1):
├─ Monitorear logs
├─ Recolectar feedback
└─ Ajustes menores

Fase 3 (Mes 1):
├─ Dashboard gerentes
├─ Reportes diarios
└─ Alertas anomalías

Fase 4 (Trimestre):
├─ Análisis tendencias
├─ Integración permisos
└─ Exportación reportes
```

---

**¡Éxito con la implementación! 🎉**

Cualquier duda → Referir a documentación correspondiente.

*Última actualización: 18-04-2026*
