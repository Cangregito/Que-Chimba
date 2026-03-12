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
