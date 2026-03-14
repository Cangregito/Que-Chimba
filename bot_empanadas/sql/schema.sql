-- ================================================================
-- schema.sql  –  Que Chimba DB  (PostgreSQL 16)
-- Crea todas las tablas del proyecto desde cero (IF NOT EXISTS).
-- ================================================================

-- Proveedores de insumos
CREATE TABLE IF NOT EXISTS proveedores (
    proveedor_id BIGSERIAL PRIMARY KEY,
    nombre        VARCHAR(120) NOT NULL,
    telefono      VARCHAR(30),
    creado_en     TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Catalogo de productos
CREATE TABLE IF NOT EXISTS productos (
    producto_id BIGSERIAL PRIMARY KEY,
    nombre      VARCHAR(120) NOT NULL,
    variante    VARCHAR(80)  NOT NULL DEFAULT '',
    precio      NUMERIC(10,2) NOT NULL,
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Historial de precios por producto
CREATE TABLE IF NOT EXISTS historial_precios (
    historial_id  BIGSERIAL PRIMARY KEY,
    producto_id   BIGINT NOT NULL REFERENCES productos(producto_id),
    precio        NUMERIC(10,2) NOT NULL,
    vigente_desde TIMESTAMP NOT NULL DEFAULT NOW(),
    vigente_hasta TIMESTAMP
);

-- Insumos / inventario
CREATE TABLE IF NOT EXISTS insumos (
    insumo_id     BIGSERIAL PRIMARY KEY,
    nombre        VARCHAR(120) NOT NULL,
    unidad_medida VARCHAR(30)  NOT NULL,
    stock_actual  NUMERIC(12,3) NOT NULL DEFAULT 0,
    stock_minimo  NUMERIC(12,3) NOT NULL DEFAULT 0,
    proveedor_id  BIGINT REFERENCES proveedores(proveedor_id)
);

-- Clientes (identificados por WhatsApp)
CREATE TABLE IF NOT EXISTS clientes (
    cliente_id  BIGSERIAL PRIMARY KEY,
    whatsapp_id VARCHAR(50) NOT NULL UNIQUE,
    nombre      VARCHAR(80) NOT NULL DEFAULT 'Cliente',
    apellidos   VARCHAR(80) NOT NULL DEFAULT 'WhatsApp',
    genero_trato VARCHAR(10) NOT NULL DEFAULT 'neutro'
);

-- Direcciones de entrega del cliente
CREATE TABLE IF NOT EXISTS direcciones_cliente (
    direccion_id   BIGSERIAL PRIMARY KEY,
    cliente_id     BIGINT NOT NULL REFERENCES clientes(cliente_id),
    latitud        NUMERIC(11,7),
    longitud       NUMERIC(11,7),
    alias          VARCHAR(80),
    direccion_texto TEXT NOT NULL DEFAULT '',
    codigo_postal  VARCHAR(5),
    referencia     TEXT,
    principal      BOOLEAN NOT NULL DEFAULT FALSE,
    actualizado_en TIMESTAMP
);

-- Datos fiscales del cliente (facturación)
CREATE TABLE IF NOT EXISTS datos_fiscales (
    fiscal_id      BIGSERIAL PRIMARY KEY,
    cliente_id     BIGINT NOT NULL REFERENCES clientes(cliente_id),
    rfc            VARCHAR(20),
    razon_social   VARCHAR(150),
    regimen_fiscal VARCHAR(80),
    uso_cfdi       VARCHAR(10),
    email          VARCHAR(120),
    actualizado_en TIMESTAMP
);

-- Pedidos
CREATE TABLE IF NOT EXISTS pedidos (
    pedido_id    BIGSERIAL PRIMARY KEY,
    cliente_id   BIGINT NOT NULL REFERENCES clientes(cliente_id),
    direccion_id BIGINT REFERENCES direcciones_cliente(direccion_id),
    metodo_pago  VARCHAR(30) NOT NULL DEFAULT 'efectivo',
    total        NUMERIC(10,2) NOT NULL DEFAULT 0,
    estado       VARCHAR(30)  NOT NULL DEFAULT 'recibido',
    creado_en    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pedidos_estado     ON pedidos (estado);
CREATE INDEX IF NOT EXISTS idx_pedidos_creado_en  ON pedidos (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_pedidos_cliente_id ON pedidos (cliente_id);

-- Detalle del pedido (items)
CREATE TABLE IF NOT EXISTS detalle_pedido (
    detalle_id      BIGSERIAL PRIMARY KEY,
    pedido_id       BIGINT NOT NULL REFERENCES pedidos(pedido_id),
    producto_id     BIGINT NOT NULL REFERENCES productos(producto_id),
    cantidad        INT           NOT NULL DEFAULT 1,
    precio_unitario NUMERIC(10,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detalle_pedido_pedido_id ON detalle_pedido (pedido_id);

-- Pagos  (efectivo y MercadoPago)
CREATE TABLE IF NOT EXISTS pagos (
    pago_id           BIGSERIAL PRIMARY KEY,
    pedido_id         BIGINT NOT NULL REFERENCES pedidos(pedido_id),
    monto             NUMERIC(10,2) NOT NULL,
    proveedor         VARCHAR(30)  NOT NULL DEFAULT 'efectivo',
    estado            VARCHAR(30)  NOT NULL DEFAULT 'pendiente',
    mp_preference_id  VARCHAR(120),
    mp_payment_id     VARCHAR(120),
    mp_status_detail  VARCHAR(120) NOT NULL DEFAULT '',
    creado_en         TIMESTAMP NOT NULL DEFAULT NOW(),
    actualizado_en    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pagos_pedido_id ON pagos (pedido_id);

-- Sesiones del bot WhatsApp (estado de conversación)
CREATE TABLE IF NOT EXISTS sesiones_bot (
    whatsapp_id    VARCHAR(50) PRIMARY KEY,
    estado         VARCHAR(50) NOT NULL DEFAULT 'inicio',
    datos_temp     JSONB        NOT NULL DEFAULT '{}',
    actualizado_en TIMESTAMP   NOT NULL DEFAULT NOW(),
    expira_en      TIMESTAMP   NOT NULL DEFAULT (NOW() + INTERVAL '5 days')
);

-- Campañas de marketing por WhatsApp
CREATE TABLE IF NOT EXISTS campanas (
    campana_id  BIGSERIAL PRIMARY KEY,
    nombre      VARCHAR(120) NOT NULL,
    mensaje     TEXT         NOT NULL,
    segmento    VARCHAR(50)  NOT NULL DEFAULT 'general',
    creada_por  VARCHAR(80),
    creado_en   TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- Empleados
CREATE TABLE IF NOT EXISTS empleados (
    empleado_id BIGSERIAL PRIMARY KEY,
    nombre      VARCHAR(80) NOT NULL,
    apellidos   VARCHAR(80) NOT NULL DEFAULT '',
    rol         VARCHAR(30) NOT NULL DEFAULT 'cocina',
    telefono    VARCHAR(30),
    activo      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Usuarios del sistema (login web por roles)
CREATE TABLE IF NOT EXISTS usuarios_sistema (
    usuario_id         BIGSERIAL PRIMARY KEY,
    username           VARCHAR(80) NOT NULL UNIQUE,
    password_hash      VARCHAR(255) NOT NULL,
    rol                VARCHAR(30) NOT NULL,
    nombre_mostrar     VARCHAR(120) NOT NULL,
    telefono           VARCHAR(30),
    area_entrega       VARCHAR(80),
    activo             BOOLEAN NOT NULL DEFAULT TRUE,
    intentos_fallidos  SMALLINT NOT NULL DEFAULT 0,
    bloqueado_hasta    TIMESTAMP,
    ultimo_login       TIMESTAMP,
    creado_en          TIMESTAMP NOT NULL DEFAULT NOW(),
    actualizado_en     TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_usuarios_sistema_rol CHECK (rol IN ('admin', 'cocina', 'repartidor')),
    CONSTRAINT chk_usuarios_sistema_hash_len CHECK (char_length(password_hash) >= 20)
);
CREATE INDEX IF NOT EXISTS idx_usuarios_sistema_rol_activo
    ON usuarios_sistema (rol, activo);
CREATE INDEX IF NOT EXISTS idx_usuarios_sistema_reparto_area
    ON usuarios_sistema (rol, area_entrega)
    WHERE activo = TRUE;

-- Auditoria de seguridad (accesos y cambios administrativos)
CREATE TABLE IF NOT EXISTS auditoria_seguridad (
    auditoria_id        BIGSERIAL PRIMARY KEY,
    tipo_evento         VARCHAR(50) NOT NULL,
    severidad           VARCHAR(15) NOT NULL DEFAULT 'info',
    actor_usuario_id    BIGINT,
    actor_username      VARCHAR(80),
    actor_rol           VARCHAR(30),
    objetivo_usuario_id BIGINT,
    objetivo_username   VARCHAR(80),
    direccion_ip        VARCHAR(64),
    detalle             JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en           TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_auditoria_seguridad_severidad CHECK (severidad IN ('info', 'warning', 'critical'))
);
CREATE INDEX IF NOT EXISTS idx_auditoria_seguridad_creado_en
    ON auditoria_seguridad (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_seguridad_tipo_evento
    ON auditoria_seguridad (tipo_evento, creado_en DESC);

-- Auditoria de negocio (operaciones criticas sobre pedidos, pagos e inventario)
CREATE TABLE IF NOT EXISTS auditoria_negocio (
    auditoria_negocio_id BIGSERIAL PRIMARY KEY,
    tabla_objetivo       VARCHAR(60) NOT NULL,
    operacion            VARCHAR(10) NOT NULL,
    registro_id          VARCHAR(120),
    actor_username       VARCHAR(80),
    actor_rol            VARCHAR(30),
    detalle              JSONB NOT NULL DEFAULT '{}'::jsonb,
    creado_en            TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_auditoria_negocio_operacion CHECK (operacion IN ('INSERT', 'UPDATE', 'DELETE'))
);
CREATE INDEX IF NOT EXISTS idx_auditoria_negocio_fecha
    ON auditoria_negocio (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_negocio_tabla
    ON auditoria_negocio (tabla_objetivo, creado_en DESC);

CREATE OR REPLACE FUNCTION fn_auditoria_negocio_generic()
RETURNS TRIGGER AS $$
DECLARE
    actor_name TEXT := NULLIF(current_setting('app.current_user', true), '');
    actor_role TEXT := NULLIF(current_setting('app.current_role', true), '');
    source_row JSONB;
    row_id TEXT;
    payload JSONB;
BEGIN
    source_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    row_id := COALESCE(
        source_row->>'pedido_id',
        source_row->>'pago_id',
        source_row->>'compra_id',
        source_row->>'insumo_id',
        source_row->>'detalle_id',
        'N/A'
    );

    IF TG_OP = 'INSERT' THEN
        payload := jsonb_build_object('new', to_jsonb(NEW));
    ELSIF TG_OP = 'UPDATE' THEN
        payload := jsonb_build_object('old', to_jsonb(OLD), 'new', to_jsonb(NEW));
    ELSE
        payload := jsonb_build_object('old', to_jsonb(OLD));
    END IF;

    INSERT INTO auditoria_negocio (tabla_objetivo, operacion, registro_id, actor_username, actor_rol, detalle)
    VALUES (TG_TABLE_NAME, TG_OP, row_id, actor_name, actor_role, payload);

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_auditoria_negocio_pedidos ON pedidos;
CREATE TRIGGER trg_auditoria_negocio_pedidos
AFTER INSERT OR UPDATE OR DELETE ON pedidos
FOR EACH ROW EXECUTE FUNCTION fn_auditoria_negocio_generic();

DROP TRIGGER IF EXISTS trg_auditoria_negocio_pagos ON pagos;
CREATE TRIGGER trg_auditoria_negocio_pagos
AFTER INSERT OR UPDATE OR DELETE ON pagos
FOR EACH ROW EXECUTE FUNCTION fn_auditoria_negocio_generic();

-- Log de notificaciones enviadas por n8n
CREATE TABLE IF NOT EXISTS log_notificaciones (
    log_id     BIGSERIAL PRIMARY KEY,
    pedido_id  BIGINT    NOT NULL,
    canal      VARCHAR(30) NOT NULL,
    destino    VARCHAR(30) NOT NULL,
    tipo       VARCHAR(30) NOT NULL,
    mensaje    TEXT        NOT NULL,
    total      NUMERIC(10,2),
    direccion  TEXT,
    creado_en  TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_log_notificaciones_pedido_id ON log_notificaciones (pedido_id);

-- Compras de inventario
CREATE TABLE IF NOT EXISTS compras_insumos (
    compra_id    BIGSERIAL PRIMARY KEY,
    insumo_id    BIGINT NOT NULL REFERENCES insumos(insumo_id),
    cantidad     NUMERIC(12,3) NOT NULL,
    costo_total  NUMERIC(10,2),
    proveedor    VARCHAR(120),
    creado_por   VARCHAR(80),
    creado_en    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_compras_insumos_insumo_id ON compras_insumos (insumo_id);

-- Recetas por producto (consumo de insumos por unidad vendida)
CREATE TABLE IF NOT EXISTS recetas_producto_insumo (
    receta_id             BIGSERIAL PRIMARY KEY,
    producto_id           BIGINT NOT NULL REFERENCES productos(producto_id),
    insumo_id             BIGINT NOT NULL REFERENCES insumos(insumo_id),
    cantidad_por_unidad   NUMERIC(12,3) NOT NULL,
    activo                BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en             TIMESTAMP NOT NULL DEFAULT NOW(),
    actualizado_en        TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_recetas_cantidad_pos CHECK (cantidad_por_unidad > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_recetas_producto_insumo_activo
    ON recetas_producto_insumo (producto_id, insumo_id);

-- Movimientos de inventario (kardex)
CREATE TABLE IF NOT EXISTS movimientos_inventario (
    movimiento_id        BIGSERIAL PRIMARY KEY,
    insumo_id            BIGINT NOT NULL REFERENCES insumos(insumo_id),
    tipo                 VARCHAR(30) NOT NULL,
    cantidad_movimiento  NUMERIC(12,3) NOT NULL,
    stock_antes          NUMERIC(12,3) NOT NULL,
    stock_despues        NUMERIC(12,3) NOT NULL,
    referencia_tipo      VARCHAR(30),
    referencia_id        BIGINT,
    detalle              JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_username       VARCHAR(80),
    actor_rol            VARCHAR(30),
    creado_en            TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_movimientos_tipo CHECK (tipo IN ('compra', 'consumo_pedido', 'ajuste_entrada', 'ajuste_salida'))
);
CREATE INDEX IF NOT EXISTS idx_movimientos_inventario_insumo
    ON movimientos_inventario (insumo_id, creado_en DESC);

DROP TRIGGER IF EXISTS trg_auditoria_negocio_insumos ON insumos;
CREATE TRIGGER trg_auditoria_negocio_insumos
AFTER INSERT OR UPDATE OR DELETE ON insumos
FOR EACH ROW EXECUTE FUNCTION fn_auditoria_negocio_generic();

DROP TRIGGER IF EXISTS trg_auditoria_negocio_compras_insumos ON compras_insumos;
CREATE TRIGGER trg_auditoria_negocio_compras_insumos
AFTER INSERT OR UPDATE OR DELETE ON compras_insumos
FOR EACH ROW EXECUTE FUNCTION fn_auditoria_negocio_generic();

-- ================================================================
-- Seeds mínimos para poder crear un pedido de prueba
-- ================================================================
INSERT INTO productos (nombre, variante, precio, activo)
VALUES
    ('Empanada de Carne',  'Normal',  15.00, TRUE),
    ('Empanada de Pollo',  'Normal',  15.00, TRUE),
    ('Empanada de Queso',  'Normal',  12.00, TRUE),
    ('Combo x6 Carne',     'Familiar', 85.00, TRUE),
    ('Empanada Especial',  'Grande',  25.00, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
VALUES
    ('Masa de maiz', 'kg', 30.000, 8.000),
    ('Carne molida', 'kg', 18.000, 6.000),
    ('Pollo deshebrado', 'kg', 14.000, 5.000),
    ('Queso', 'kg', 12.000, 4.000),
    ('Aceite', 'lt', 25.000, 6.000)
ON CONFLICT DO NOTHING;

INSERT INTO recetas_producto_insumo (producto_id, insumo_id, cantidad_por_unidad, activo)
SELECT p.producto_id, i.insumo_id, x.cantidad_por_unidad, TRUE
FROM (
    VALUES
        ('Empanada de Carne', 'Masa de maiz', 0.080::NUMERIC),
        ('Empanada de Carne', 'Carne molida', 0.070::NUMERIC),
        ('Empanada de Pollo', 'Masa de maiz', 0.080::NUMERIC),
        ('Empanada de Pollo', 'Pollo deshebrado', 0.070::NUMERIC),
        ('Empanada de Queso', 'Masa de maiz', 0.080::NUMERIC),
        ('Empanada de Queso', 'Queso', 0.060::NUMERIC),
        ('Empanada Especial', 'Masa de maiz', 0.110::NUMERIC),
        ('Empanada Especial', 'Queso', 0.050::NUMERIC),
        ('Combo x6 Carne', 'Masa de maiz', 0.480::NUMERIC),
        ('Combo x6 Carne', 'Carne molida', 0.420::NUMERIC)
) AS x(producto_nombre, insumo_nombre, cantidad_por_unidad)
JOIN productos p ON p.nombre = x.producto_nombre
JOIN insumos i ON i.nombre = x.insumo_nombre
ON CONFLICT (producto_id, insumo_id)
DO UPDATE SET
    cantidad_por_unidad = EXCLUDED.cantidad_por_unidad,
    activo = TRUE,
    actualizado_en = NOW();

INSERT INTO empleados (nombre, apellidos, rol, telefono, activo)
VALUES
    ('Juan',    'Cocina',     'cocina',      NULL, TRUE),
    ('Maria',   'Reparto',    'repartidor',  NULL, TRUE),
    ('Admin',   'Sistema',    'admin',       NULL, TRUE)
ON CONFLICT DO NOTHING;
