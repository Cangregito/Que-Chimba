# Hardening SQL Pack (sin downtime)

Este paquete aplica hardening incremental en PostgreSQL para seguridad, rendimiento y trazabilidad.

## Orden de ejecucion

1. 01_roles_app_minimo_privilegio.sql
2. 02_indices_online_concurrently.sql
3. 03_constraints_not_valid_y_validate.sql
4. 04_auditoria_triggers_catalogo.sql
5. 05_rls_fase1_policies.sql

## Modo de ejecucion recomendado

Cada script debe ejecutarse por separado con psql.
No mezclar todos en una sola transaccion.

Ejemplo (PowerShell):

psql -U postgres -d que_chimba -f bot_empanadas/sql/migrations_hardening_2026_04/01_roles_app_minimo_privilegio.sql

## Importante sobre locks

- Los indices se crean con CONCURRENTLY para evitar bloqueo de escritura largo.
- Las constraints se agregan como NOT VALID y se validan en sentencia separada.
- RLS se habilita al final del pack para minimizar riesgo operativo.

## Requisitos previos

- Definir un usuario de app dedicado (app_que_chimba)
- Tener un mantenimiento corto para observar metricas durante fase RLS
- Respaldar antes de ejecutar

## Verificacion rapida post-migracion

SELECT schemaname, tablename, indexname
FROM pg_indexes
WHERE tablename IN ('pagos', 'asignaciones_reparto', 'detalle_pedido', 'pedidos')
ORDER BY tablename, indexname;

SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class
WHERE relname IN ('pedidos', 'pagos', 'direcciones_cliente');

SELECT conname, convalidated
FROM pg_constraint
WHERE conname IN (
  'chk_pedidos_total_nonneg',
  'chk_detalle_pedido_cantidad_pos',
  'chk_detalle_pedido_precio_nonneg',
  'chk_pagos_monto_nonneg'
)
ORDER BY conname;
