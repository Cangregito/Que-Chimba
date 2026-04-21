-- 04_auditoria_triggers_catalogo.sql
-- Amplia cobertura de auditoria para catalogo y precios.

DROP TRIGGER IF EXISTS trg_auditoria_negocio_productos ON productos;
CREATE TRIGGER trg_auditoria_negocio_productos
AFTER INSERT OR UPDATE OR DELETE ON productos
FOR EACH ROW EXECUTE FUNCTION fn_auditoria_negocio_generic();

DROP TRIGGER IF EXISTS trg_auditoria_negocio_historial_precios ON historial_precios;
CREATE TRIGGER trg_auditoria_negocio_historial_precios
AFTER INSERT OR UPDATE OR DELETE ON historial_precios
FOR EACH ROW EXECUTE FUNCTION fn_auditoria_negocio_generic();

DROP TRIGGER IF EXISTS trg_auditoria_negocio_recetas ON recetas_producto_insumo;
CREATE TRIGGER trg_auditoria_negocio_recetas
AFTER INSERT OR UPDATE OR DELETE ON recetas_producto_insumo
FOR EACH ROW EXECUTE FUNCTION fn_auditoria_negocio_generic();
