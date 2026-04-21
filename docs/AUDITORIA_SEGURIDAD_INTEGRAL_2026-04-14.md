# Auditoría de Seguridad Integral — Que Chimba

Fecha: 2026-04-14

## Alcance

Auditoría estática y de configuración sobre el proyecto académico local Que Chimba.

Componentes revisados:
- Flask web y API
- Bridge WhatsApp con Baileys
- Integración de pagos
- Scripts operativos y backups
- Manejo de datos sensibles, logs y roles

## Resumen ejecutivo

Estado general: base de seguridad aceptable para entorno académico local controlado, pero todavía no apto para despliegue serio en producción sin hardening adicional.

Fortalezas verificadas:
- Control de acceso por rol en paneles web
- Hash de contraseñas con Werkzeug
- Bloqueo temporal por intentos fallidos
- Parametrización SQL mayoritariamente correcta
- Cifrado en reposo para datos sensibles con pgcrypto cuando existe SENSITIVE_DATA_KEY
- Hash SHA-256 e integridad de backups

Riesgos prioritarios:
1. Cookies de sesión no seguras por defecto
2. Webhook público sin autenticación fuerte en flujo legacy
3. Exposición de PII en logs operativos
4. Ausencia de validación de firma para callbacks de MercadoPago
5. Dependencia Node con hallazgos críticos reportados por npm audit

## Matriz de riesgos

| ID | Riesgo | Severidad | Probabilidad | Estado |
| --- | --- | --- | --- | --- |
| R1 | Sesión Flask sin cookie secure por defecto | Alta | Alta | Abierto |
| R2 | Webhook público legacy sin firma/autenticación | Alta | Media | Abierto |
| R3 | Logs con teléfonos, transcripciones y referencias de cliente | Alta | Alta | Abierto |
| R4 | Callback de MercadoPago sin validación criptográfica de origen | Alta | Media | Abierto |
| R5 | Dependencia axios vulnerable a SSRF / exfiltración | Crítica | Media | Abierto |
| R6 | Token del bridge opcional fuera de producción | Media | Media | Parcial |
| R7 | Audios/medios temporales con limpieza pero sin límites de tamaño | Media | Media | Parcial |
| R8 | Secretos sensibles manejados por entorno local y scripts | Media | Media | Parcial |
| R9 | Directorios de auth/media/backups contienen material sensible operativo | Media | Media | Parcial |
| R10 | Sin protección CSRF formal en formularios web | Media | Media | Abierto |
| R11 | SQL injection en capa principal | Baja | Baja | Mitigado |
| R12 | Cifrado en reposo de GPS y datos fiscales | Baja | Baja | Mitigado |

## Hallazgos verificados

### 1. Autenticación y autorización

Hallazgos positivos:
- Las rutas web críticas usan decorador de login por rol en [bot_empanadas/routes/common_routes.py](bot_empanadas/routes/common_routes.py#L68-L145).
- La autenticación consulta usuarios de base de datos, usa hash de contraseña y bloqueo temporal en [bot_empanadas/db.py](bot_empanadas/db.py#L1661-L1789).

Riesgos:
- La cookie de sesión usa HTTPOnly y SameSite, pero SESSION_COOKIE_SECURE queda en falso por defecto en [bot_empanadas/app.py](bot_empanadas/app.py#L141-L143).
- No se observó protección CSRF dedicada con Flask-WTF o equivalente para formularios y acciones POST del panel.
- FLASK_SECRET se genera automáticamente si no existe; esto protege desarrollo, pero debilita la disciplina operativa si alguien despliega sin secret persistente en [bot_empanadas/app.py](bot_empanadas/app.py#L130-L164).

### 2. Credenciales y secretos

Hallazgos positivos:
- El proyecto documenta variables críticas en [README.md](README.md#L123-L139).
- El arranque en [run_all.ps1](run_all.ps1#L187-L244) enmascara parte de las claves al mostrarlas.

Riesgos:
- Los scripts operativos siguen usando DB_PASSWORD como variable de entorno de sesión en [run_all.ps1](run_all.ps1#L210-L244) y [scripts/ops/backup_postgres.ps1](scripts/ops/backup_postgres.ps1#L1-L60).
- Existen tokens operativos para Bridge, MercadoPago y TTS que dependen de la higiene del entorno local.
- El archivo [.gitignore](.gitignore) protege secretos, pero el directorio real de auth Baileys existe en el workspace y debe tratarse como altamente sensible.

### 3. Inyección SQL y validación de datos

Hallazgos positivos:
- La capa DB usa psycopg2 con parámetros y uso de identificadores seguros en múltiples consultas, por ejemplo en [bot_empanadas/db.py](bot_empanadas/db.py#L68-L126).
- La autenticación y muchas operaciones usan placeholders y no concatenación directa.

Riesgos:
- No encontré una inyección SQL crítica obvia en la capa principal revisada.
- El vector más realista viene por datos de WhatsApp, audio y texto libre; aunque se parametriza SQL, falta endurecer límites de longitud y listas blancas a nivel HTTP.

### 4. MercadoPago y terceros

Riesgos:
- La integración crea notification_url hacia webhook de pago en [bot_empanadas/payments.py](bot_empanadas/payments.py#L89-L116), pero no se encontró validación de firma o cabecera de autenticidad del callback.
- El bridge y Flask usan token simple por cabecera para integrarse internamente, lo cual es correcto para entorno local, pero debe reforzarse si escala.

### 5. Comunicación y transporte

Riesgos:
- El proyecto está orientado a localhost y HTTP en defaults. PUBLIC_BASE_URL y bridge usan HTTP por defecto en [bot_empanadas/config_runtime.py](bot_empanadas/config_runtime.py#L1-L8).
- Si se publica sin TLS reverso, las sesiones y callbacks quedarían expuestos.

### 6. Datos sensibles y privacidad

Hallazgos positivos:
- Existe bootstrap de pgcrypto y cifrado en reposo con SENSITIVE_DATA_KEY para direcciones y datos fiscales en [bot_empanadas/db.py](bot_empanadas/db.py#L146-L233).
- Hay memoria técnica del hardening sensible ya aplicada.

Riesgos:
- Se registran teléfonos, trazas y transcripciones de audio en logs, por ejemplo en [bot_empanadas/routes/webhook_routes.py](bot_empanadas/routes/webhook_routes.py#L58-L103) y [bot_empanadas/bot.py](bot_empanadas/bot.py#L702-L724).
- Los audios temporales se limpian por TTL, pero permanecen durante horas en disco en [bot_empanadas/voice.py](bot_empanadas/voice.py#L24-L60).

### 7. Archivos sensibles y backups

Hallazgos positivos:
- Backups se ignoran en git mediante [.gitignore](.gitignore).
- Se genera hash SHA-256 en [scripts/ops/backup_postgres.ps1](scripts/ops/backup_postgres.ps1#L331-L343) y se verifica restauración en [scripts/ops/verify_restore_postgres.ps1](scripts/ops/verify_restore_postgres.ps1#L180-L184).

Riesgos:
- Los directorios [backups/postgres](backups/postgres), [baileys_bridge/auth](baileys_bridge/auth) y [baileys_bridge/media_tmp](baileys_bridge/media_tmp) contienen material sensible operativo y deben restringirse a nivel filesystem.

### 8. Logging y auditoría

Hallazgos positivos:
- Existe auditoría de seguridad y negocio con eventos relevantes en base de datos.
- El sistema separa logs de aplicación y handler PostgreSQL en [bot_empanadas/logging_handlers.py](bot_empanadas/logging_handlers.py#L1-L31).

Riesgos:
- No hay sanitización fuerte de PII antes de persistir o imprimir mensajes de error y observabilidad.
- Los errores 500 registran excepción completa en [bot_empanadas/app.py](bot_empanadas/app.py#L450-L456).

### 9. Dependencias

Resultado verificado:
- Python: sin conflictos de dependencias instaladas mediante pip check.
- Node: npm audit reportó 4 vulnerabilidades, incluyendo 1 crítica en axios, 1 alta en path-to-regexp y 2 moderadas indirectas.

## Vulnerabilidades identificadas con evidencia

| Tipo | Evidencia | Riesgo |
| --- | --- | --- |
| Cookie de sesión insegura por defecto | [bot_empanadas/app.py](bot_empanadas/app.py#L141-L143) | Robo de sesión en despliegue HTTP |
| Secret temporal autogenerado | [bot_empanadas/app.py](bot_empanadas/app.py#L130-L164) | Inestabilidad y mala práctica operativa |
| Webhook Baileys con token simple | [bot_empanadas/routes/webhook_routes.py](bot_empanadas/routes/webhook_routes.py#L42-L52) | Correcto para local, débil para exposición pública |
| Webhook legado sin firma visible | [bot_empanadas/routes/webhook_routes.py](bot_empanadas/routes/webhook_routes.py#L11-L40) | Suplantación de requests |
| Logs con PII y transcripción | [bot_empanadas/bot.py](bot_empanadas/bot.py#L702-L724) | Fuga de datos personales |
| Audios temporales persistidos 24h | [bot_empanadas/voice.py](bot_empanadas/voice.py#L24-L60) | Exposición local de notas de voz |
| Callback MercadoPago sin firma hallada | [bot_empanadas/payments.py](bot_empanadas/payments.py#L89-L116) | Falsificación de estado de pago |
| Riesgos de dependencias Node | [baileys_bridge/package.json](baileys_bridge/package.json) | SSRF y DoS por librerías vulnerables |

## Recomendaciones priorizadas

### Prioridad 1 — inmediata

1. Forzar cookie segura y endurecer sesión
- Definir SESSION_COOKIE_SECURE=true
- Añadir expiración explícita de sesión
- Invalidar sesión al cambiar rol/credenciales

2. Proteger todos los webhooks públicos
- Validar firma real del proveedor para WhatsApp legacy y MercadoPago
- Mantener token interno del bridge y rotarlo periódicamente
- Rechazar requests sin timestamp o sin origen confiable

3. Reducir exposición de PII en logs
- Enmascarar teléfono, GPS, RUC/RFC y textos transcritos
- Evitar loguear contenido completo del usuario en nivel info

4. Corregir dependencias Node
- Actualizar axios a versión segura actual
- Regenerar lockfile y repetir auditoría

### Prioridad 2 — corta

5. Añadir protección CSRF real para paneles web
6. Aplicar límites de tamaño a audio, JSON y uploads
7. Restringir permisos NTFS sobre auth, backups y logs
8. Centralizar secretos fuera de variables persistentes visibles

### Prioridad 3 — mejora continua

9. Completar políticas RLS para más tablas sensibles
10. Añadir rotación automática de tokens de integración
11. Implementar monitoreo de accesos administrativos anómalos
12. Documentar perfil de despliegue seguro dev vs prod

## Checklist de hardening

### Aplicación Flask
- [ ] SESSION_COOKIE_SECURE en verdadero en cualquier entorno publicado
- [ ] Tiempo de vida de sesión definido
- [ ] CSRF en formularios y acciones de panel
- [ ] FLASK_SECRET obligatorio en cualquier despliegue no local

### Webhooks e integraciones
- [ ] Firma de MercadoPago validada
- [ ] Firma o autenticación fuerte en webhook público de WhatsApp
- [ ] Rotación de BAILEYS_WEBHOOK_TOKEN y BAILEYS_BRIDGE_API_TOKEN
- [ ] Lista de IPs/orígenes confiables cuando aplique

### Datos sensibles
- [ ] SENSITIVE_DATA_KEY obligatoria fuera de demo local
- [ ] Redacción de PII en logs
- [ ] TTL más corto para audios temporales
- [ ] Política de borrado seguro de medios temporales

### PostgreSQL
- [ ] Usuario app con mínimo privilegio en todos los entornos
- [ ] Revisar RLS fase 2
- [ ] Verificación periódica de restore real
- [ ] Permisos restringidos sobre dumps y carpetas de backup

### Bridge Baileys
- [ ] Actualizar dependencias vulnerables
- [ ] Mantener auth y media fuera de rutas compartidas
- [ ] Limitar tamaño de payload y media descargada
- [ ] No exponer el bridge directamente a Internet sin proxy/TLS

## Configuración segura sugerida para producción

Variables mínimas recomendadas:
- APP_ENV=production
- FLASK_SECRET con alta entropía y persistente
- SESSION_COOKIE_SECURE=true
- SESSION_COOKIE_SAMESITE=Lax o Strict según flujo
- PUBLIC_BASE_URL sobre HTTPS
- BAILEYS_WEBHOOK_TOKEN aleatorio y largo
- BAILEYS_BRIDGE_API_TOKEN aleatorio y largo
- SENSITIVE_DATA_KEY obligatoria
- MP_ACCESS_TOKEN solo desde secreto del entorno
- ELEVENLABS_API_KEY solo desde secreto del entorno
- DB_PASSWORD no persistida en texto plano en scripts

Controles de infraestructura:
- Proxy reverso con TLS
- Restricción por firewall a puertos internos
- Permisos NTFS mínimos en auth, logs y backups
- Rotación de backups validada con restore periódico

## Conclusión

Conclusión de auditoría: el proyecto muestra una base madura para un entorno académico local y ya incorpora varias buenas prácticas reales. Sin embargo, antes de considerarlo para una operación más expuesta deben resolverse de forma prioritaria los puntos de cookies seguras, validación fuerte de webhooks, reducción de PII en logs y actualización de dependencias del bridge.

Nivel global estimado actual:
- Entorno académico local controlado: aceptable con mejoras recomendadas
- Entorno semiabierto o productivo: no recomendado aún sin hardening adicional
