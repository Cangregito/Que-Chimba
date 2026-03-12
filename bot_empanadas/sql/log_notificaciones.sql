-- Tabla para auditoria de alertas n8n/WhatsApp
CREATE TABLE IF NOT EXISTS log_notificaciones (
  log_id BIGSERIAL PRIMARY KEY,
  pedido_id BIGINT NOT NULL,
  canal VARCHAR(30) NOT NULL,
  destino VARCHAR(30) NOT NULL,
  tipo VARCHAR(30) NOT NULL,
  mensaje TEXT NOT NULL,
  total NUMERIC(10,2),
  direccion TEXT,
  creado_en TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_log_notificaciones_pedido_id
  ON log_notificaciones (pedido_id);
