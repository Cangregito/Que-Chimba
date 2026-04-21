# Plan de hardening DB + seguridad (sin downtime)

Fecha: 2026-04-13
Alcance: PostgreSQL, backend Flask, webhooks y operacion.

## Fase 0 (pre-check, 30-60 min)

Objetivo:
- Reducir riesgo antes de tocar produccion.

Acciones:
1. Respaldar base de datos completa.
2. Confirmar que existe ventana de observacion (logs, errores, tiempos de respuesta).
3. Confirmar variables de entorno criticas: FLASK_SECRET, BAILEYS_WEBHOOK_TOKEN, SENSITIVE_DATA_KEY.

Criterio de salida:
- Backup validado y capacidad de rollback lista.

## Fase 1 (48 horas)

Objetivo:
- Mitigar vectores de alto impacto sin interrupcion.

Acciones SQL (orden exacto):
1. 01_roles_app_minimo_privilegio.sql
2. 02_indices_online_concurrently.sql
3. 03_constraints_not_valid_y_validate.sql
4. 04_auditoria_triggers_catalogo.sql

Acciones backend:
1. Forzar BAILEYS_WEBHOOK_TOKEN en produccion (fail fast al iniciar).
2. Forzar SENSITIVE_DATA_KEY en produccion (fail fast al iniciar).
3. Migrar SQL dinamico de identificadores a psycopg2.sql.Identifier en helper de updates.

Criterio de salida:
- Sin errores de login ni webhooks.
- Reportes y APIs de pedidos respondiendo en latencia normal.
- Constraints validadas y nuevos indices activos.

## Fase 2 (2 semanas)

Objetivo:
- Activar aislamiento fuerte por rol en la base.

Acciones SQL:
1. 05_rls_fase1_policies.sql

Acciones backend obligatorias:
1. Garantizar set_config por request/transaccion:
   - app.current_user
   - app.current_role
2. Ejecutar smoke tests de rutas:
   - admin
   - cocina
   - repartidor
3. Validar que repartidor solo vea pedidos asignados.

Criterio de salida:
- No hay fuga horizontal de datos entre repartidores.
- No hay errores por politicas RLS en flujos de negocio.

## Fase 3 (1 mes)

Objetivo:
- Escalabilidad enterprise y madurez operativa.

Acciones:
1. Introducir pool de conexiones (ThreadedConnectionPool o PgBouncer).
2. Separar carga analitica:
   - materialized views para reportes pesados
   - refresh programado
3. Revisar retencion y minimizacion de PII en tablas y logs.
4. Completar pruebas de resiliencia:
   - picos de mensajes concurrentes
   - fallos temporales de DB

Criterio de salida:
- p95 estable en endpoints operativos bajo carga.
- Reportes no impactan flujo transaccional.

## Comandos de ejecucion sugeridos (PowerShell)

psql -U postgres -d que_chimba -f bot_empanadas/sql/migrations_hardening_2026_04/01_roles_app_minimo_privilegio.sql
psql -U postgres -d que_chimba -f bot_empanadas/sql/migrations_hardening_2026_04/02_indices_online_concurrently.sql
psql -U postgres -d que_chimba -f bot_empanadas/sql/migrations_hardening_2026_04/03_constraints_not_valid_y_validate.sql
psql -U postgres -d que_chimba -f bot_empanadas/sql/migrations_hardening_2026_04/04_auditoria_triggers_catalogo.sql
psql -U postgres -d que_chimba -f bot_empanadas/sql/migrations_hardening_2026_04/05_rls_fase1_policies.sql

## Rollback rapido (guia minima)

1. RLS:
- ALTER TABLE <tabla> DISABLE ROW LEVEL SECURITY;
- DROP POLICY ...;

2. Triggers de auditoria nuevos:
- DROP TRIGGER ... ON productos/historial_precios/recetas_producto_insumo;

3. Constraints nuevas:
- ALTER TABLE ... DROP CONSTRAINT ...;

4. Indices nuevos:
- DROP INDEX CONCURRENTLY ...;

5. Rol app:
- REVOKE grants y luego DROP ROLE app_que_chimba (solo si ya no se usa).

## Evidencia post-cambio

Guardar salida de:
1. EXPLAIN (ANALYZE, BUFFERS) de:
   - top clientes
   - reporte ventas profesional
   - pedidos repartidor
2. SELECT de pg_indexes y pg_constraint.
3. Pruebas funcionales por rol (admin/cocina/repartidor).
