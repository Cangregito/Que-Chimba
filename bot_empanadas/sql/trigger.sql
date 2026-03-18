-- ============================================================================
-- trigger.sql - Inventario automatico y validaciones para Que Chimba Empanadas
--
-- Este script implementa:
-- 1) Funcion de descuento automatico de insumos por cada item vendido.
-- 2) Trigger AFTER INSERT en detalle_pedido.
-- 3) Funcion verificar_stock_suficiente(producto_id, cantidad).
-- 4) Funcion generar_codigo_entrega() de 6 caracteres (sin O ni 0).
-- 5) Seed inicial de insumos con stock minimo oficial.
-- ============================================================================

BEGIN;

-- --------------------------------------------------------------------------
-- Tabla de alertas de inventario para dashboard de cocina.
-- Se inserta una alerta cuando el stock baja del minimo configurado.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alertas_inventario (
    alerta_id BIGSERIAL PRIMARY KEY,
    insumo_id BIGINT NOT NULL REFERENCES insumos(insumo_id),
    nombre_insumo VARCHAR(120) NOT NULL,
    stock_actual NUMERIC(12,3) NOT NULL,
    stock_minimo NUMERIC(12,3) NOT NULL,
    mensaje TEXT NOT NULL,
    creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
    atendida BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_alertas_inventario_atendida
    ON alertas_inventario(atendida, creado_en DESC);

-- --------------------------------------------------------------------------
-- Asegurar columna y unicidad para codigo de entrega en pedidos.
-- --------------------------------------------------------------------------
ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS codigo_entrega VARCHAR(6);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_codigo_entrega
    ON pedidos(codigo_entrega)
    WHERE codigo_entrega IS NOT NULL;

-- --------------------------------------------------------------------------
-- Funcion interna: descuenta un insumo y genera alerta si queda bajo minimo.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION _descontar_insumo_y_alertar(
    p_nombre_insumo TEXT,
    p_cantidad NUMERIC
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_insumo RECORD;
    v_nuevo_stock NUMERIC(12,3);
BEGIN
    IF p_cantidad IS NULL OR p_cantidad <= 0 THEN
        RETURN;
    END IF;

        SELECT insumo_id, nombre, stock_actual, stock_minimo
    INTO v_insumo
    FROM insumos
        WHERE lower(translate(nombre, 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) =
            lower(translate(p_nombre_insumo, 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'))
    ORDER BY insumo_id
    LIMIT 1
    FOR UPDATE;

    -- Si no existe el insumo, no detenemos la venta; se deja registro para revision.
    IF NOT FOUND THEN
        INSERT INTO alertas_inventario(insumo_id, nombre_insumo, stock_actual, stock_minimo, mensaje)
        VALUES (0, p_nombre_insumo, 0, 0, 'Insumo no encontrado para descuento automatico');
        RETURN;
    END IF;

    v_nuevo_stock := COALESCE(v_insumo.stock_actual, 0) - p_cantidad;

    UPDATE insumos
    SET stock_actual = v_nuevo_stock
    WHERE insumo_id = v_insumo.insumo_id;

    IF v_nuevo_stock <= COALESCE(v_insumo.stock_minimo, 0) THEN
        INSERT INTO alertas_inventario(
            insumo_id,
            nombre_insumo,
            stock_actual,
            stock_minimo,
            mensaje
        )
        VALUES (
            v_insumo.insumo_id,
            v_insumo.nombre,
            v_nuevo_stock,
            COALESCE(v_insumo.stock_minimo, 0),
            format('Stock bajo minimo para %s: actual=%s minimo=%s', v_insumo.nombre, v_nuevo_stock, COALESCE(v_insumo.stock_minimo, 0))
        );
    END IF;
END;
$$;

-- --------------------------------------------------------------------------
-- 1) Funcion principal de descuento por producto.
-- Se ejecuta por cada INSERT en detalle_pedido.
--
-- Reglas exactas de consumo (Seccion B):
-- Empanada carne (id=1):
--   Harina de maiz -100g, Carne molida -50g, Aceite vegetal -5ml,
--   Sal -2g, Cebolla -8g, Tomate -8g, Ajo -2g, Comino -0.5g, Empaque/bolsa -1.
-- Empanada pollo (id=2):
--   Harina de maiz -100g, Pechuga de pollo -50g, Aceite vegetal -5ml,
--   Sal -2g, Cebolla -8g, Tomate -8g, Ajo -2g, Comino -0.5g, Empaque/bolsa -1.
-- Agua (id=3):      -1 botella
-- Refresco (id=4):  -1 lata
-- Jugo (id=5):      -150g fruta/pulpa
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION descontar_insumos_por_producto()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_qty NUMERIC(12,3);
BEGIN
    v_qty := COALESCE(NEW.cantidad, 0);

    IF v_qty <= 0 THEN
        RETURN NEW;
    END IF;

    IF NEW.producto_id = 1 THEN
        PERFORM _descontar_insumo_y_alertar('Harina de maíz',   100 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Carne molida',      50 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Aceite vegetal',     5 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Sal',                2 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Cebolla',            8 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Tomate',             8 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Ajo',                2 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Comino',           0.5 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Empaque/bolsa',      1 * v_qty);

    ELSIF NEW.producto_id = 2 THEN
        PERFORM _descontar_insumo_y_alertar('Harina de maíz',   100 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Pechuga de pollo',  50 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Aceite vegetal',     5 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Sal',                2 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Cebolla',            8 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Tomate',             8 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Ajo',                2 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Comino',           0.5 * v_qty);
        PERFORM _descontar_insumo_y_alertar('Empaque/bolsa',      1 * v_qty);

    ELSIF NEW.producto_id = 3 THEN
        PERFORM _descontar_insumo_y_alertar('Agua 500ml',         1 * v_qty);

    ELSIF NEW.producto_id = 4 THEN
        PERFORM _descontar_insumo_y_alertar('Refresco lata',      1 * v_qty);

    ELSIF NEW.producto_id = 5 THEN
        PERFORM _descontar_insumo_y_alertar('Jugo fruta/pulpa', 150 * v_qty);
    END IF;

    RETURN NEW;
END;
$$;

-- --------------------------------------------------------------------------
-- 2) Trigger AFTER INSERT ON detalle_pedido
-- --------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_descontar_insumos_detalle_pedido ON detalle_pedido;

CREATE TRIGGER trg_descontar_insumos_detalle_pedido
AFTER INSERT ON detalle_pedido
FOR EACH ROW
EXECUTE FUNCTION descontar_insumos_por_producto();

-- --------------------------------------------------------------------------
-- 3) Funcion verificar_stock_suficiente(producto_id, cantidad)
--
-- Devuelve TRUE si hay stock suficiente para ese producto/cantidad.
-- Devuelve FALSE si falta cualquiera de sus insumos.
--
-- Nota: esta funcion se usa antes de crear el pedido para prevenir sobreventa.
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION verificar_stock_suficiente(
    p_producto_id BIGINT,
    p_cantidad NUMERIC
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_req_harina NUMERIC := 0;
    v_req_carne NUMERIC := 0;
    v_req_pollo NUMERIC := 0;
    v_req_aceite NUMERIC := 0;
    v_req_sal NUMERIC := 0;
    v_req_cebolla NUMERIC := 0;
    v_req_tomate NUMERIC := 0;
    v_req_ajo NUMERIC := 0;
    v_req_comino NUMERIC := 0;
    v_req_empaque NUMERIC := 0;
    v_req_agua NUMERIC := 0;
    v_req_refresco NUMERIC := 0;
    v_req_jugo NUMERIC := 0;
BEGIN
    IF p_cantidad IS NULL OR p_cantidad <= 0 THEN
        RETURN FALSE;
    END IF;

    IF p_producto_id = 1 THEN
        v_req_harina := 100 * p_cantidad;
        v_req_carne := 50 * p_cantidad;
        v_req_aceite := 5 * p_cantidad;
        v_req_sal := 2 * p_cantidad;
        v_req_cebolla := 8 * p_cantidad;
        v_req_tomate := 8 * p_cantidad;
        v_req_ajo := 2 * p_cantidad;
        v_req_comino := 0.5 * p_cantidad;
        v_req_empaque := 1 * p_cantidad;

    ELSIF p_producto_id = 2 THEN
        v_req_harina := 100 * p_cantidad;
        v_req_pollo := 50 * p_cantidad;
        v_req_aceite := 5 * p_cantidad;
        v_req_sal := 2 * p_cantidad;
        v_req_cebolla := 8 * p_cantidad;
        v_req_tomate := 8 * p_cantidad;
        v_req_ajo := 2 * p_cantidad;
        v_req_comino := 0.5 * p_cantidad;
        v_req_empaque := 1 * p_cantidad;

    ELSIF p_producto_id = 3 THEN
        v_req_agua := 1 * p_cantidad;

    ELSIF p_producto_id = 4 THEN
        v_req_refresco := 1 * p_cantidad;

    ELSIF p_producto_id = 5 THEN
        v_req_jugo := 150 * p_cantidad;

    ELSE
        RETURN FALSE;
    END IF;

    RETURN
        (v_req_harina   = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(translate(nombre, 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'))=lower(translate('Harina de maíz', 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) ORDER BY insumo_id LIMIT 1), 0) >= v_req_harina)
    AND (v_req_carne    = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Carne molida')     ORDER BY insumo_id LIMIT 1), 0) >= v_req_carne)
    AND (v_req_pollo    = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Pechuga de pollo') ORDER BY insumo_id LIMIT 1), 0) >= v_req_pollo)
    AND (v_req_aceite   = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Aceite vegetal')   ORDER BY insumo_id LIMIT 1), 0) >= v_req_aceite)
    AND (v_req_sal      = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Sal')              ORDER BY insumo_id LIMIT 1), 0) >= v_req_sal)
    AND (v_req_cebolla  = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Cebolla')          ORDER BY insumo_id LIMIT 1), 0) >= v_req_cebolla)
    AND (v_req_tomate   = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Tomate')           ORDER BY insumo_id LIMIT 1), 0) >= v_req_tomate)
    AND (v_req_ajo      = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Ajo')              ORDER BY insumo_id LIMIT 1), 0) >= v_req_ajo)
    AND (v_req_comino   = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Comino')           ORDER BY insumo_id LIMIT 1), 0) >= v_req_comino)
    AND (v_req_empaque  = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Empaque/bolsa')    ORDER BY insumo_id LIMIT 1), 0) >= v_req_empaque)
    AND (v_req_agua     = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Agua 500ml')       ORDER BY insumo_id LIMIT 1), 0) >= v_req_agua)
    AND (v_req_refresco = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Refresco lata')    ORDER BY insumo_id LIMIT 1), 0) >= v_req_refresco)
    AND (v_req_jugo     = 0 OR COALESCE((SELECT stock_actual FROM insumos WHERE lower(nombre)=lower('Jugo fruta/pulpa') ORDER BY insumo_id LIMIT 1), 0) >= v_req_jugo);
END;
$$;

-- --------------------------------------------------------------------------
-- 4) Funcion generar_codigo_entrega()
-- 6 caracteres unicos: mayusculas + numeros (sin O ni 0).
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION generar_codigo_entrega()
RETURNS VARCHAR(6)
LANGUAGE plpgsql
AS $$
DECLARE
    v_chars CONSTANT TEXT := 'ABCDEFGHJKLMNPQRSTUVWXYZ123456789';
    v_code TEXT;
    i INT;
BEGIN
    FOR i IN 1..80 LOOP
        v_code := '';
        v_code := v_code || substr(v_chars, 1 + floor(random() * length(v_chars))::INT, 1);
        v_code := v_code || substr(v_chars, 1 + floor(random() * length(v_chars))::INT, 1);
        v_code := v_code || substr(v_chars, 1 + floor(random() * length(v_chars))::INT, 1);
        v_code := v_code || substr(v_chars, 1 + floor(random() * length(v_chars))::INT, 1);
        v_code := v_code || substr(v_chars, 1 + floor(random() * length(v_chars))::INT, 1);
        v_code := v_code || substr(v_chars, 1 + floor(random() * length(v_chars))::INT, 1);

        IF NOT EXISTS (
            SELECT 1
            FROM pedidos
            WHERE codigo_entrega = v_code
        ) THEN
            RETURN v_code;
        END IF;
    END LOOP;

    -- Fallback de emergencia; practicamente no deberia ocurrir.
    RETURN upper(substr(md5(random()::text), 1, 6));
END;
$$;

-- --------------------------------------------------------------------------
-- 5) Seed inicial de insumos con minimos oficiales de la Seccion B.
--
-- Nota: si ya existen registros por nombre, solo se actualiza stock_minimo.
-- Si no existen, se crean con stock_actual inicial igual al minimo.
-- --------------------------------------------------------------------------
INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Harina de maíz', 'g', 2000, 2000
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Harina de maíz'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Carne molida', 'g', 500, 500
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Carne molida'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Pechuga de pollo', 'g', 500, 500
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Pechuga de pollo'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Aceite vegetal', 'ml', 200, 200
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Aceite vegetal'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Sal', 'g', 200, 100
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Sal'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Cebolla', 'g', 1000, 300
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Cebolla'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Tomate', 'g', 1000, 300
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Tomate'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Ajo', 'g', 300, 100
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Ajo'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Comino', 'g', 100, 30
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Comino'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Empaque/bolsa', 'unidad', 50, 50
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Empaque/bolsa'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Agua 500ml', 'botella', 24, 24
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Agua 500ml'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Refresco lata', 'lata', 24, 24
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Refresco lata'));

INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo)
SELECT 'Jugo fruta/pulpa', 'g', 600, 600
WHERE NOT EXISTS (SELECT 1 FROM insumos WHERE lower(nombre)=lower('Jugo fruta/pulpa'));

UPDATE insumos
SET stock_minimo = 2000
WHERE lower(translate(nombre, 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU')) =
    lower(translate('Harina de maíz', 'áéíóúÁÉÍÓÚ', 'aeiouAEIOU'));
UPDATE insumos SET stock_minimo = 500  WHERE lower(nombre)=lower('Carne molida');
UPDATE insumos SET stock_minimo = 500  WHERE lower(nombre)=lower('Pechuga de pollo');
UPDATE insumos SET stock_minimo = 200  WHERE lower(nombre)=lower('Aceite vegetal');
UPDATE insumos SET stock_minimo = 24   WHERE lower(nombre)=lower('Agua 500ml');
UPDATE insumos SET stock_minimo = 24   WHERE lower(nombre)=lower('Refresco lata');
UPDATE insumos SET stock_minimo = 600  WHERE lower(nombre)=lower('Jugo fruta/pulpa');
UPDATE insumos SET stock_minimo = 50   WHERE lower(nombre)=lower('Empaque/bolsa');

COMMIT;
