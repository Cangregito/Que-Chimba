-- 01_roles_app_minimo_privilegio.sql
-- Ejecutar como superuser o admin de base de datos.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_que_chimba') THEN
        CREATE ROLE app_que_chimba
            LOGIN
            PASSWORD 'CAMBIAR_POR_SECRETO_FUERTE'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE que_chimba TO app_que_chimba;
GRANT USAGE ON SCHEMA public TO app_que_chimba;

GRANT SELECT, INSERT, UPDATE ON
    clientes,
    direcciones_cliente,
    datos_fiscales,
    pedidos,
    detalle_pedido,
    pagos,
    sesiones_bot,
    asignaciones_reparto,
    bitacora_estado_pedidos,
    auditoria_seguridad,
    auditoria_negocio,
    insumos,
    compras_insumos,
    movimientos_inventario,
    log_notificaciones
TO app_que_chimba;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_que_chimba;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT, INSERT, UPDATE ON TABLES TO app_que_chimba;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES TO app_que_chimba;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE que_chimba FROM PUBLIC;
