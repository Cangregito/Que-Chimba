-- 05_rls_fase1_policies.sql
-- Fase 1 RLS: habilitar y definir politicas base.
-- Requiere que backend setee:
--   set_config('app.current_user', <username>, true)
--   set_config('app.current_role', <rol>, true)

ALTER TABLE pedidos ENABLE ROW LEVEL SECURITY;
ALTER TABLE pedidos FORCE ROW LEVEL SECURITY;

ALTER TABLE direcciones_cliente ENABLE ROW LEVEL SECURITY;
ALTER TABLE direcciones_cliente FORCE ROW LEVEL SECURITY;

ALTER TABLE pagos ENABLE ROW LEVEL SECURITY;
ALTER TABLE pagos FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pedidos_admin_all ON pedidos;
CREATE POLICY pedidos_admin_all
ON pedidos
FOR ALL
USING (current_setting('app.current_role', true) = 'admin')
WITH CHECK (current_setting('app.current_role', true) = 'admin');

DROP POLICY IF EXISTS pedidos_repartidor_read ON pedidos;
CREATE POLICY pedidos_repartidor_read
ON pedidos
FOR SELECT
USING (
    current_setting('app.current_role', true) = 'repartidor'
    AND EXISTS (
        SELECT 1
        FROM asignaciones_reparto ar
        WHERE ar.pedido_id = pedidos.pedido_id
          AND ar.repartidor_usuario = current_setting('app.current_user', true)
          AND ar.activo = TRUE
    )
);

DROP POLICY IF EXISTS direcciones_admin_all ON direcciones_cliente;
CREATE POLICY direcciones_admin_all
ON direcciones_cliente
FOR ALL
USING (current_setting('app.current_role', true) = 'admin')
WITH CHECK (current_setting('app.current_role', true) = 'admin');

DROP POLICY IF EXISTS direcciones_repartidor_read ON direcciones_cliente;
CREATE POLICY direcciones_repartidor_read
ON direcciones_cliente
FOR SELECT
USING (
    current_setting('app.current_role', true) = 'repartidor'
    AND EXISTS (
        SELECT 1
        FROM pedidos p
        JOIN asignaciones_reparto ar ON ar.pedido_id = p.pedido_id
        WHERE p.direccion_id = direcciones_cliente.direccion_id
          AND ar.repartidor_usuario = current_setting('app.current_user', true)
          AND ar.activo = TRUE
    )
);

DROP POLICY IF EXISTS pagos_admin_all ON pagos;
CREATE POLICY pagos_admin_all
ON pagos
FOR ALL
USING (current_setting('app.current_role', true) = 'admin')
WITH CHECK (current_setting('app.current_role', true) = 'admin');
