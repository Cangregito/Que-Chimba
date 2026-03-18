-- =========================================================
-- queries_jurado.sql
-- Consultas de presentacion para jurado - Proyecto Que Chimba
-- PostgreSQL 16
-- =========================================================

-- Opcional para salida legible en demo:
-- \timing on
-- \x off

-- Parametro opcional para la consulta #7 (historial de precios)
-- Puedes cambiarlo en vivo: \set producto_id 1
\set producto_id 1

-- 1) Top 20 clientes con mas compras (JOIN clientes + pedidos)
-- Demuestra segmentacion comercial: quienes compran mas y cuanto facturan.
SELECT
    c.cliente_id,
    c.whatsapp_id,
    c.nombre,
    c.apellidos,
    COUNT(p.pedido_id) AS total_pedidos,
    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS monto_total_comprado,
    MAX(p.creado_en) AS ultima_compra
FROM clientes c
JOIN pedidos p ON p.cliente_id = c.cliente_id
WHERE p.estado <> 'cancelado'
GROUP BY c.cliente_id, c.whatsapp_id, c.nombre, c.apellidos
ORDER BY monto_total_comprado DESC, total_pedidos DESC
LIMIT 20;

-- 2) Ventas del dia actual agrupadas por hora
-- Demuestra comportamiento operativo por franja horaria (picos de demanda).
SELECT
    DATE_TRUNC('hour', p.creado_en) AS hora,
    COUNT(*) AS pedidos,
    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
FROM pedidos p
WHERE p.estado <> 'cancelado'
  AND p.creado_en::date = CURRENT_DATE
GROUP BY DATE_TRUNC('hour', p.creado_en)
ORDER BY hora;

-- 3) Ventas del mes agrupadas por dia (ideal para grafica de barras)
-- Demuestra tendencia diaria de ingresos durante el mes en curso.
SELECT
    DATE_TRUNC('day', p.creado_en)::date AS dia,
    COUNT(*) AS pedidos,
    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
FROM pedidos p
WHERE p.estado <> 'cancelado'
  AND DATE_TRUNC('month', p.creado_en) = DATE_TRUNC('month', CURRENT_DATE)
GROUP BY DATE_TRUNC('day', p.creado_en)::date
ORDER BY dia;

-- 4) Ventas del ano agrupadas por mes
-- Demuestra estacionalidad y crecimiento mensual del negocio.
SELECT
    TO_CHAR(DATE_TRUNC('month', p.creado_en), 'YYYY-MM') AS mes,
    COUNT(*) AS pedidos,
    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
FROM pedidos p
WHERE p.estado <> 'cancelado'
  AND DATE_TRUNC('year', p.creado_en) = DATE_TRUNC('year', CURRENT_DATE)
GROUP BY DATE_TRUNC('month', p.creado_en)
ORDER BY DATE_TRUNC('month', p.creado_en);

-- 5) Productos mas vendidos con total de ingresos por producto
-- Demuestra rentabilidad y rotacion por producto/variante.
SELECT
    pr.producto_id,
    pr.nombre,
    pr.variante,
    SUM(dp.cantidad) AS unidades_vendidas,
    COALESCE(SUM(dp.cantidad * dp.precio_unitario), 0)::NUMERIC(12,2) AS ingresos_totales
FROM detalle_pedido dp
JOIN productos pr ON pr.producto_id = dp.producto_id
JOIN pedidos p ON p.pedido_id = dp.pedido_id
WHERE p.estado <> 'cancelado'
GROUP BY pr.producto_id, pr.nombre, pr.variante
ORDER BY unidades_vendidas DESC, ingresos_totales DESC;

-- 6) Stock de insumos por debajo del minimo (alertas)
-- Demuestra control de inventario preventivo para evitar quiebres de stock.
SELECT
    i.insumo_id,
    i.nombre,
    i.unidad_medida,
    i.stock_actual,
    i.stock_minimo,
    (i.stock_minimo - i.stock_actual)::NUMERIC(10,3) AS faltante,
    pv.nombre AS proveedor
FROM insumos i
LEFT JOIN proveedores pv ON pv.proveedor_id = i.proveedor_id
WHERE i.stock_actual < i.stock_minimo
ORDER BY faltante DESC, i.nombre;

-- 7) Historial completo de cambios de precio de un producto
-- Demuestra trazabilidad historica de precios y vigencias.
SELECT
    pr.producto_id,
    pr.nombre,
    pr.variante,
    hp.precio,
    hp.vigente_desde,
    hp.vigente_hasta,
    CASE
        WHEN hp.vigente_hasta IS NULL THEN 'vigente_actual'
        ELSE 'historico'
    END AS estado_vigencia
FROM historial_precios hp
JOIN productos pr ON pr.producto_id = hp.producto_id
WHERE hp.producto_id = :producto_id
ORDER BY hp.vigente_desde DESC;

-- 8) Pedidos por estado (dashboard de cocina)
-- Demuestra carga operativa actual y cuello de botella en el flujo.
SELECT
    p.estado,
    COUNT(*) AS total_pedidos
FROM pedidos p
GROUP BY p.estado
ORDER BY CASE p.estado
    WHEN 'recibido' THEN 1
    WHEN 'en_preparacion' THEN 2
    WHEN 'listo' THEN 3
    WHEN 'en_camino' THEN 4
    WHEN 'entregado' THEN 5
    WHEN 'cancelado' THEN 6
    ELSE 99
END;

-- 9) Clientes que NO han comprado en los ultimos 30 dias
-- Demuestra segmentacion para campanas de reactivacion por WhatsApp.
SELECT
    c.cliente_id,
    c.whatsapp_id,
    c.nombre,
    c.apellidos,
    MAX(p.creado_en) AS ultima_compra
FROM clientes c
LEFT JOIN pedidos p
    ON p.cliente_id = c.cliente_id
   AND p.estado <> 'cancelado'
GROUP BY c.cliente_id, c.whatsapp_id, c.nombre, c.apellidos
HAVING MAX(p.creado_en) IS NULL
    OR MAX(p.creado_en) < (NOW() - INTERVAL '30 days')
ORDER BY ultima_compra NULLS FIRST, c.cliente_id;

-- 10) Corte del dia: total efectivo, total tarjeta, total general
-- Demuestra cierre financiero diario por metodo de pago.
SELECT
    COALESCE(SUM(CASE WHEN pa.proveedor = 'efectivo' THEN pa.monto END), 0)::NUMERIC(12,2) AS total_efectivo,
    COALESCE(SUM(CASE WHEN pa.proveedor = 'mercadopago' THEN pa.monto END), 0)::NUMERIC(12,2) AS total_tarjeta,
    COALESCE(SUM(pa.monto), 0)::NUMERIC(12,2) AS total_general
FROM pagos pa
WHERE pa.estado = 'completado'
  AND pa.creado_en::date = CURRENT_DATE;

-- 11) Validacion del trigger SQL de inventario (ruta crear_pedido_completo)
-- Demuestra efecto operativo del trigger: ventas recientes implican consumo teorico,
-- y se observa el stock actual junto con alertas de inventario generadas.
WITH consumo_7d AS (
    SELECT
        rpi.insumo_id,
        SUM(dp.cantidad * rpi.cantidad_por_unidad)::NUMERIC(12,3) AS consumo_estimado_7d
    FROM detalle_pedido dp
    JOIN pedidos p ON p.pedido_id = dp.pedido_id
    JOIN recetas_producto_insumo rpi
        ON rpi.producto_id = dp.producto_id
       AND rpi.activo = TRUE
    WHERE p.estado <> 'cancelado'
      AND p.creado_en >= NOW() - INTERVAL '7 days'
    GROUP BY rpi.insumo_id
),
alertas_7d AS (
    SELECT
        ai.insumo_id,
        COUNT(*) AS alertas_7d,
        MAX(ai.creado_en) AS ultima_alerta
    FROM alertas_inventario ai
    WHERE ai.creado_en >= NOW() - INTERVAL '7 days'
    GROUP BY ai.insumo_id
)
SELECT
    i.insumo_id,
    i.nombre AS insumo,
    i.unidad_medida,
    i.stock_actual::NUMERIC(12,3) AS stock_actual,
    i.stock_minimo::NUMERIC(12,3) AS stock_minimo,
    COALESCE(c.consumo_estimado_7d, 0)::NUMERIC(12,3) AS consumo_estimado_7d,
    COALESCE(a.alertas_7d, 0) AS alertas_7d,
    a.ultima_alerta,
    CASE
        WHEN i.stock_actual <= 0 THEN 'AGOTADO'
        WHEN i.stock_actual < i.stock_minimo THEN 'BAJO_MINIMO'
        ELSE 'OK'
    END AS estado_stock
FROM insumos i
LEFT JOIN consumo_7d c ON c.insumo_id = i.insumo_id
LEFT JOIN alertas_7d a ON a.insumo_id = i.insumo_id
ORDER BY
    CASE
        WHEN i.stock_actual <= 0 THEN 0
        WHEN i.stock_actual < i.stock_minimo THEN 1
        ELSE 2
    END,
    COALESCE(a.alertas_7d, 0) DESC,
    i.nombre;

-- 12) Auditoria de negocio: ultimos 30 eventos criticos
-- Demuestra trazabilidad completa: quien cambio que, cuando y desde que IP.
SELECT
    an.evento_id,
    an.tabla_afectada,
    an.operacion,
    an.actor_usuario,
    an.actor_rol,
    an.registro_id,
    an.cambios,
    an.ejecutado_en
FROM auditoria_negocio an
ORDER BY an.ejecutado_en DESC
LIMIT 30;

-- 13) Rentabilidad estimada por producto
-- Demuestra calculo de margen bruto usando recetas + ultimo costo de insumos.
-- Permite identificar cuales productos son mas rentables para el negocio.
SELECT
    pr.producto_id,
    pr.nombre,
    pr.variante,
    pr.precio                                          AS precio_venta,
    COALESCE(
        SUM(rpi.cantidad_por_unidad * ci.precio_unitario_promedio), 0
    )::NUMERIC(10,2)                                   AS costo_estimado,
    (pr.precio - COALESCE(
        SUM(rpi.cantidad_por_unidad * ci.precio_unitario_promedio), 0
    ))::NUMERIC(10,2)                                  AS margen_bruto,
    CASE
        WHEN pr.precio > 0 THEN
            ROUND(
                ((pr.precio - COALESCE(
                    SUM(rpi.cantidad_por_unidad * ci.precio_unitario_promedio), 0
                )) / pr.precio * 100)::NUMERIC, 2
            )
        ELSE 0
    END                                                AS margen_pct
FROM productos pr
LEFT JOIN recetas_producto_insumo rpi
       ON rpi.producto_id = pr.producto_id AND rpi.activo = TRUE
LEFT JOIN (
    SELECT
        ci2.insumo_id,
        AVG(ci2.costo_total / NULLIF(ci2.cantidad, 0))::NUMERIC(10,4) AS precio_unitario_promedio
    FROM compras_insumos ci2
    WHERE ci2.cantidad > 0
    GROUP BY ci2.insumo_id
) ci ON ci.insumo_id = rpi.insumo_id
WHERE pr.activo = TRUE
GROUP BY pr.producto_id, pr.nombre, pr.variante, pr.precio
ORDER BY margen_pct DESC NULLS LAST;

-- 14) Estado actual del inventario vs minimos operativos
-- Demuestra vision en tiempo real de la bodega: stock actual, dias de cobertura
-- estimados segun consumo promedio de los ultimos 7 dias y alertas de quiebre.
SELECT
    i.insumo_id,
    i.nombre,
    i.unidad_medida,
    i.stock_actual::NUMERIC(12,3)                        AS stock_actual,
    i.stock_minimo::NUMERIC(12,3)                        AS stock_minimo,
    COALESCE(consumo.consumo_7d, 0)::NUMERIC(12,3)       AS consumo_ultimos_7d,
    CASE
        WHEN COALESCE(consumo.consumo_7d, 0) > 0 THEN
            ROUND((i.stock_actual / (consumo.consumo_7d / 7))::NUMERIC, 1)
        ELSE NULL
    END                                                  AS dias_cobertura_est,
    CASE
        WHEN i.stock_actual <= 0                     THEN 'AGOTADO'
        WHEN i.stock_actual  < i.stock_minimo        THEN 'CRITICO'
        WHEN i.stock_actual  < i.stock_minimo * 1.5  THEN 'BAJO'
        ELSE                                              'OK'
    END                                                  AS alerta
FROM insumos i
LEFT JOIN (
    SELECT
        mi2.insumo_id,
        SUM(ABS(mi2.cantidad_movimiento)) AS consumo_7d
    FROM movimientos_inventario mi2
    WHERE mi2.tipo = 'consumo_pedido'
      AND mi2.creado_en >= NOW() - INTERVAL '7 days'
    GROUP BY mi2.insumo_id
) consumo ON consumo.insumo_id = i.insumo_id
ORDER BY
    CASE
        WHEN i.stock_actual <= 0             THEN 0
        WHEN i.stock_actual < i.stock_minimo THEN 1
        ELSE 2
    END,
    i.nombre;

-- 15) Sesiones activas del bot por estado FSM
-- Demuestra el flujo en tiempo real: cuantos clientes estan en cada etapa
-- del proceso de compra y cuando fue su ultima interaccion.
SELECT
    sb.estado,
    COUNT(*)                                  AS clientes_en_estado,
    MIN(sb.ultima_actualizacion)              AS mas_antigua,
    MAX(sb.ultima_actualizacion)              AS mas_reciente,
    COUNT(*) FILTER (
        WHERE sb.ultima_actualizacion >= NOW() - INTERVAL '15 minutes'
    )                                         AS activos_ultimos_15min
FROM sesiones_bot sb
WHERE sb.expira_en IS NULL OR sb.expira_en > NOW()
GROUP BY sb.estado
ORDER BY clientes_en_estado DESC, sb.estado;
