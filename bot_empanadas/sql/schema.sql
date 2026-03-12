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
    apellidos   VARCHAR(80) NOT NULL DEFAULT 'WhatsApp'
);

-- Direcciones de entrega del cliente
CREATE TABLE IF NOT EXISTS direcciones_cliente (
    direccion_id   BIGSERIAL PRIMARY KEY,
    cliente_id     BIGINT NOT NULL REFERENCES clientes(cliente_id),
    latitud        NUMERIC(11,7),
    longitud       NUMERIC(11,7),
    alias          VARCHAR(80),
    direccion_texto TEXT NOT NULL DEFAULT '',
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

INSERT INTO empleados (nombre, apellidos, rol, telefono, activo)
VALUES
    ('Juan',    'Cocina',     'cocina',      NULL, TRUE),
    ('Maria',   'Reparto',    'repartidor',  NULL, TRUE),
    ('Admin',   'Sistema',    'admin',       NULL, TRUE)
ON CONFLICT DO NOTHING;
