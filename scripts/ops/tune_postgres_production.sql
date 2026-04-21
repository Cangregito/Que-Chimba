-- Tuning PostgreSQL para produccion - Que Chimba
-- 16 GB RAM, SSD, PostgreSQL 16
-- Aplicar con: psql -U postgres -f tune_postgres_production.sql
-- Requiere: pg_ctl restart despues de aplicar

ALTER SYSTEM SET shared_buffers          = '512MB';
ALTER SYSTEM SET work_mem                = '16MB';
ALTER SYSTEM SET maintenance_work_mem    = '256MB';
ALTER SYSTEM SET effective_cache_size    = '12GB';
ALTER SYSTEM SET random_page_cost        = 1.1;
ALTER SYSTEM SET wal_buffers             = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET log_min_duration_statement   = 1000;
ALTER SYSTEM SET shared_preload_libraries     = 'pg_stat_statements';
ALTER SYSTEM SET autovacuum_vacuum_scale_factor   = 0.05;
ALTER SYSTEM SET autovacuum_analyze_scale_factor  = 0.02;

SELECT name, setting, unit,
       CASE name
         WHEN 'shared_buffers'       THEN '-> 512MB (era 128MB)'
         WHEN 'work_mem'             THEN '-> 16MB  (era 4MB)'
         WHEN 'effective_cache_size' THEN '-> 12GB  (era defecto)'
         WHEN 'random_page_cost'     THEN '-> 1.1   (era 4, HDD default)'
         WHEN 'wal_buffers'          THEN '-> 64MB  (era 4MB)'
         ELSE ''
       END AS cambio
FROM pg_settings
WHERE name IN (
  'shared_buffers','work_mem','maintenance_work_mem',
  'effective_cache_size','random_page_cost','wal_buffers',
  'log_min_duration_statement','shared_preload_libraries',
  'autovacuum_vacuum_scale_factor','autovacuum_analyze_scale_factor'
)
ORDER BY name;
