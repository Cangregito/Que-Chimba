-- 03_constraints_not_valid_y_validate.sql
-- Estrategia online: ADD CONSTRAINT NOT VALID + VALIDATE CONSTRAINT.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_pedidos_total_nonneg'
    ) THEN
        ALTER TABLE pedidos
            ADD CONSTRAINT chk_pedidos_total_nonneg CHECK (total >= 0) NOT VALID;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_detalle_pedido_cantidad_pos'
    ) THEN
        ALTER TABLE detalle_pedido
            ADD CONSTRAINT chk_detalle_pedido_cantidad_pos CHECK (cantidad > 0) NOT VALID;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_detalle_pedido_precio_nonneg'
    ) THEN
        ALTER TABLE detalle_pedido
            ADD CONSTRAINT chk_detalle_pedido_precio_nonneg CHECK (precio_unitario >= 0) NOT VALID;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_pagos_monto_nonneg'
    ) THEN
        ALTER TABLE pagos
            ADD CONSTRAINT chk_pagos_monto_nonneg CHECK (monto >= 0) NOT VALID;
    END IF;
END
$$;

ALTER TABLE pedidos VALIDATE CONSTRAINT chk_pedidos_total_nonneg;
ALTER TABLE detalle_pedido VALIDATE CONSTRAINT chk_detalle_pedido_cantidad_pos;
ALTER TABLE detalle_pedido VALIDATE CONSTRAINT chk_detalle_pedido_precio_nonneg;
ALTER TABLE pagos VALIDATE CONSTRAINT chk_pagos_monto_nonneg;
