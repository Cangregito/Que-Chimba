-- 02_indices_online_concurrently.sql
-- IMPORTANTE: CREATE INDEX CONCURRENTLY no puede correr dentro de BEGIN/COMMIT.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pagos_mp_preference_id
ON pagos (mp_preference_id)
WHERE mp_preference_id IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pagos_mp_payment_id
ON pagos (mp_payment_id)
WHERE mp_payment_id IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_asignaciones_reparto_usuario_activo
ON asignaciones_reparto (repartidor_usuario, activo, pedido_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_detalle_pedido_producto_id
ON detalle_pedido (producto_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pedidos_estado_creado_en
ON pedidos (estado, creado_en DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pedidos_cliente_estado_creado_en
ON pedidos (cliente_id, estado, creado_en DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sesiones_bot_expira_en
ON sesiones_bot (expira_en);
