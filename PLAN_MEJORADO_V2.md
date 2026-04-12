# PLAN MEJORADO Y REFACTORIZADO
## Sistema de Backups + Logs de Errores Unificado

**Versión:** 2.0 (Corregida)  
**Fecha:** 12-04-2026  
**Compatibilidad:** ✅ 100% con backup_postgres.ps1 actual  
**Duración Estimada:** 4-5 horas (implementación + testing)

---

## 🎯 OBJETIVOS CORREGIDOS

1. ✅ **Integrar OneDrive** al backup actual (NO reescribir)
2. ✅ **Sistema de Logs Unificado** sin imports circulares
3. ✅ **Dashboard Admin** con paginación real y búsqueda
4. ✅ **Validación de Cuota** antes de copiar a OneDrive
5. ✅ **Rate-Limiting** en logger para evitar spam
6. ✅ **No bloquear Task Scheduler** si OneDrive no responde

---

## PARTE 1 - EXTENDER backup_postgres.ps1 CON ONEDRIVE

### 1A. Agregar función Get-OneDrivePath

```powershell
# INSERTAR después de la función Send-AlertWhatsApp (línea ~180)

function Get-OneDrivePath {
    <#
    .SYNOPSIS
        Detecta la ruta de OneDrive en Windows (automático, robusto)
    #>
    # Intentar variables de entorno primero
    $paths = @(
        $env:OneDrive,
        $env:OneDriveConsumer,
        $env:OneDriveCommercial,
        "$env:USERPROFILE\OneDrive",
        "$env:USERPROFILE\OneDrive - Personal"
    )
    
    foreach ($p in $paths) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            return $p
        }
    }
    
    # Intentar desde registro de Windows
    $regPath = "HKCU:\Software\Microsoft\OneDrive\Accounts"
    if (Test-Path -LiteralPath $regPath) {
        $accounts = Get-ChildItem -LiteralPath $regPath -ErrorAction SilentlyContinue
        foreach ($acc in $accounts) {
            $userFolder = (Get-ItemProperty -Path $acc.PSPath -Name "UserFolder" -ErrorAction SilentlyContinue).UserFolder
            if ($userFolder -and (Test-Path -LiteralPath $userFolder)) {
                return $userFolder
            }
        }
    }
    
    return $null
}

function Test-OneDriveSpace {
    <#
    .SYNOPSIS
        Valida que OneDrive tenga espacio disponible (mínimo 500MB)
    #>
    param([string]$OneDrivePath, [int]$MinMB = 500)
    
    if (-not (Test-Path -LiteralPath $OneDrivePath)) {
        return $false
    }
    
    try {
        $drive = (Get-Item -LiteralPath $OneDrivePath).PSDrive.Name
        $free = (Get-PSDrive -Name $drive).Free
        return $free -ge ($MinMB * 1MB)
    }
    catch {
        return $false
    }
}

function Copy-ToOneDrive {
    <#
    .SYNOPSIS
        Copia backup a OneDrive sin bloquear (async-friendly).
    .PARAMETER ZipPath
        Ruta del archivo .zip comprimido
    .PARAMETER JsonPath
        Ruta del archivo .json metadata
    .PARAMETER BackupFolder
        Carpeta dentro de OneDrive (daily/weekly/monthly)
    #>
    param(
        [string]$ZipPath,
        [string]$JsonPath,
        [string]$BackupFolder = "daily"
    )
    
    if (-not (Test-Path -LiteralPath $ZipPath)) {
        Write-Log "ERROR" "Archivo ZIP no existe: $ZipPath"
        return $false
    }
    
    $onedrive = Get-OneDrivePath
    if (-not $onedrive) {
        Write-Log "WARN" "OneDrive no detectado, saltando copia"
        return $false
    }
    
    if (-not (Test-OneDriveSpace -OneDrivePath $onedrive)) {
        Write-Log "WARN" "OneDrive usa >95% espacio o no tiene 500MB libres"
        return $false
    }
    
    $destDir = Join-Path $onedrive "Backups\QueChimba\$BackupFolder"
    
    try {
        $null = New-Item -ItemType Directory -Path $destDir -Force
        
        # Copiar ZIP
        $zipDest = Join-Path $destDir (Split-Path -Leaf $ZipPath)
        Copy-Item -LiteralPath $ZipPath -Destination $zipDest -Force
        
        # Copiar JSON metadata
        if (Test-Path -LiteralPath $JsonPath) {
            $jsonDest = Join-Path $destDir (Split-Path -Leaf $JsonPath)
            Copy-Item -LiteralPath $JsonPath -Destination $jsonDest -Force
        }
        
        # Verificar integridad (misma forma que local)
        $localSize = (Get-Item -LiteralPath $ZipPath).Length
        $cloudSize = (Get-Item -LiteralPath $zipDest -ErrorAction SilentlyContinue)?.Length
        
        if ($cloudSize -ne $localSize) {
            Write-Log "ERROR" "Tamaño diferente OneDrive. Local: $localSize, Cloud: $cloudSize. Reintentando..."
            Copy-Item -LiteralPath $ZipPath -Destination $zipDest -Force
            Start-Sleep -Milliseconds 500
            $cloudSize = (Get-Item -LiteralPath $zipDest).Length
        }
        
        if ($cloudSize -eq $localSize) {
            Write-Log "INFO" "Copiado a OneDrive: $(Split-Path -Leaf $ZipPath) ($([math]::Round($cloudSize/1MB, 2))MB)"
            return $true
        } else {
            Write-Log "ERROR" "OneDrive copia falló después de reintento"
            return $false
        }
    }
    catch {
        Write-Log "ERROR" "Erro al copiar a OneDrive: $($_.Exception.Message)"
        return $false
    }
}

function Clean-OneDriveBackups {
    <#
    .SYNOPSIS
        Limpia backups viejos en OneDrive (sin bloquear si falla)
    #>
    param(
        [int]$DailyRetentionDays = 7,
        [int]$WeeklyRetentionDays = 28
    )
    
    $onedrive = Get-OneDrivePath
    if (-not $onedrive) { return }
    
    $baseDir = Join-Path $onedrive "Backups\QueChimba"
    if (-not (Test-Path -LiteralPath $baseDir)) { return }
    
    try {
        # Limpiar daily (7 días)
        $dailyDir = Join-Path $baseDir "daily"
        if (Test-Path -LiteralPath $dailyDir) {
            $cutoff = (Get-Date).AddDays(-$DailyRetentionDays)
            Get-ChildItem -LiteralPath $dailyDir -Filter "backup_*.zip" -File |
                Where-Object { $_.LastWriteTime -lt $cutoff } |
                ForEach-Object {
                    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
                    Remove-Item -LiteralPath (Join-Path $dailyDir ($_.BaseName + ".json")) -Force -ErrorAction SilentlyContinue
                    Write-Log "INFO" "OneDrive daily eliminado: $($_.Name)"
                }
        }
        
        # Limpiar weekly (28 días)
        $weeklyDir = Join-Path $baseDir "weekly"
        if (Test-Path -LiteralPath $weeklyDir) {
            $cutoff = (Get-Date).AddDays(-$WeeklyRetentionDays)
            Get-ChildItem -LiteralPath $weeklyDir -Filter "backup_*.zip" -File |
                Where-Object { $_.LastWriteTime -lt $cutoff } |
                ForEach-Object {
                    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
                    Remove-Item -LiteralPath (Join-Path $weeklyDir ($_.BaseName + ".json")) -Force -ErrorAction SilentlyContinue
                    Write-Log "INFO" "OneDrive weekly eliminado: $($_.Name)"
                }
        }
        
        # Monthly: NUNCA se borra (retención indefinida)
    }
    catch {
        Write-Log "WARN" "Error limpiando OneDrive: $($_.Exception.Message)"
        # No propagar error
    }
}
```

### 1B. Integrar en el flujo principal

```powershell
# MODIFICAR en el bloque try del script principal (después de generar el ZIP)

    # Después de: Compress-Archive y Remove-Item $sqlPath

    Write-Log "INFO" "Copiando a OneDrive..."
    $onedriveCopyOk = Copy-ToOneDrive -ZipPath $zipPath -JsonPath $jsonPath -BackupFolder "daily"
    
    # Rotación semanal (si es domingo)
    if ((Get-Date).DayOfWeek -eq "Sunday") {
        Copy-ToOneDrive -ZipPath $zipPath -JsonPath $jsonPath -BackupFolder "weekly"
    }
    
    # Rotación mensual (si es día 1)
    if ((Get-Date).Day -eq 1) {
        Copy-ToOneDrive -ZipPath $zipPath -JsonPath $jsonPath -BackupFolder "monthly"
    }
    
    # Limpiar backups viejos en OneDrive (sin bloquear si falla)
    Clean-OneDriveBackups -DailyRetentionDays 7 -WeeklyRetentionDays 28
    
    # Resto del código continúa sin cambios...
```

---

## PARTE 2 - SISTEMA DE LOGS SIN CIRCULAR IMPORTS

### 2A. Crear logging_handlers.py (NUEVO ARCHIVO)

```python
# RUTA: bot_empanadas/logging_handlers.py
# Este archivo SEPARA los handlers para evitar imports circulares

import logging
import os

class PostgreSQLHandler(logging.Handler):
    """
    Handler personalizado que guarda logs WARNING+ en PostgreSQL.
    Nunca lanza excepción aunque la BD esté caída (fail silently).
    """
    
    def __init__(self, componente: str):
        super().__init__()
        self.componente = componente
    
    def emit(self, record: logging.LogRecord):
        try:
            # Import tardío para evitar circular imports
            from db import insertar_log
            
            insertar_log(
                nivel=record.levelname,
                componente=self.componente,
                funcion=record.funcName,
                mensaje=self.format(record)[:500],  # Truncar a 500 chars
                detalle=record.exc_text if record.exc_info else None,
                whatsapp_id=getattr(record, 'whatsapp_id', None),
                pedido_id=getattr(record, 'pedido_id', None),
                ip_origen=getattr(record, 'ip_origen', None),
                duracion_ms=getattr(record, 'duracion_ms', None),
            )
        except Exception:
            # El logger NUNCA puede romper el flujo principal
            pass


class RateLimitedHandler(logging.Handler):
    """
    Handler que reduce spam evitando logs duplicados en corto tiempo.
    """
    
    def __init__(self, min_interval_seconds: float = 0.1):
        super().__init__()
        self.min_interval = min_interval_seconds
        self._last_log = {}
    
    def emit(self, record: logging.LogRecord):
        import time
        
        key = f"{record.name}:{record.msg}"
        now = time.time()
        
        if key in self._last_log and (now - self._last_log[key]) < self.min_interval:
            return  # Skip si hace menos de min_interval
        
        self._last_log[key] = now
        # El log se propaga al siguiente handler en la cadena
```

### 2B. Crear logger.py REFACTORIZADO

```python
# RUTA: bot_empanadas/logger.py
# Refactorizado para usar logging_handlers y evitar circular imports

import logging
import os
from datetime import datetime
from functools import wraps
from logging_handlers import PostgreSQLHandler, RateLimitedHandler

# ──── CONFIGURACIÓN ────────────────────────────────
LOG_DIR = os.environ.get('LOG_DIR', r'C:\QuéChimba\logs')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

os.makedirs(LOG_DIR, exist_ok=True)

FORMATO = '%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s'
FECHA_FORMATO = '%Y-%m-%d %H:%M:%S'


def configurar_logger(nombre_componente: str) -> logging.Logger:
    """
    Crea un logger configurado para un componente específico.
    
    Escribe en:
    1. Archivo rotativo: logs/componente_YYYY-MM.log
    2. Consola (stderr)
    3. PostgreSQL (solo WARNING y superior)
    """
    logger = logging.getLogger(nombre_componente)
    logger.setLevel(getattr(logging, LOG_LEVEL))
    
    if logger.handlers:  # Evitar duplicar handlers
        return logger
    
    # Handler 1: Archivo rotativo mensual
    archivo = os.path.join(
        LOG_DIR, f"{nombre_componente}_{datetime.now().strftime('%Y-%m')}.log"
    )
    fh = logging.FileHandler(archivo, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FORMATO, FECHA_FORMATO))
    logger.addHandler(fh)
    
    # Handler 2: Consola
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(FORMATO, FECHA_FORMATO))
    logger.addHandler(ch)
    
    # Handler 3: Rate-limited para evitar spam
    rl = RateLimitedHandler(min_interval_seconds=0.1)
    rl.setLevel(logging.DEBUG)
    logger.addHandler(rl)
    
    # Handler 4: PostgreSQL (solo WARNING+)
    pg_handler = PostgreSQLHandler(nombre_componente)
    pg_handler.setLevel(logging.WARNING)
    logger.addHandler(pg_handler)
    
    return logger


def log_error(logger, mensaje: str, exc: Exception = None, **contexto):
    """
    Atajo para loggear errores con contexto adicional.
    
    Uso: log_error(logger, "Falló STT", exc, whatsapp_id='521234')
    """
    extra = {k: v for k, v in contexto.items()
             if k in ('whatsapp_id', 'pedido_id', 'ip_origen', 'duracion_ms')}
    
    if exc:
        logger.error(mensaje, exc_info=exc, extra=extra)
    else:
        logger.error(mensaje, extra=extra)


def medir_tiempo(logger, nombre_operacion: str):
    """
    Decorador que mide el tiempo de ejecución de una función
    y lo registra en el log.
    
    Uso: @medir_tiempo(logger, 'transcribir_audio')
    def transcribir_audio(...):
        ...
    """
    def decorador(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            inicio = datetime.now()
            try:
                resultado = func(*args, **kwargs)
                duracion = int((datetime.now() - inicio).total_seconds() * 1000)
                
                if duracion > 3000:  # Log si tarda más de 3s
                    logger.warning(
                        f"{nombre_operacion} tardó {duracion}ms (lento)",
                        extra={'duracion_ms': duracion}
                    )
                
                return resultado
            except Exception as e:
                duracion = int((datetime.now() - inicio).total_seconds() * 1000)
                log_error(logger, f"Error en {nombre_operacion}", e,
                         duracion_ms=duracion)
                raise
        return wrapper
    return decorador
```

### 2C. Crear db.py CON FUNCIONES DE LOG

```python
# AGREGAR a bot_empanadas/db.py (al final del archivo)

def insertar_log(nivel, componente, funcion, mensaje,
                detalle=None, whatsapp_id=None,
                pedido_id=None, ip_origen=None,
                duracion_ms=None):
    """
    Inserta un registro en logs_sistema.
    Diseñada para ser llamada por PostgreSQLHandler.
    NUNCA lanza excepción — falla silenciosamente.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO logs_sistema
                    (nivel, componente, funcion, mensaje,
                     detalle, whatsapp_id, pedido_id,
                     ip_origen, duracion_ms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (nivel, componente, funcion, mensaje,
                      detalle, whatsapp_id, pedido_id,
                      ip_origen, duracion_ms))
                conn.commit()
    except Exception:
        pass  # No propagar — el logger no puede romper la app


def obtener_logs(nivel=None, componente=None,
                limite=100, offset=0, solo_no_resueltos=False):
    """
    Para el dashboard admin. Con OFFSET para paginación.
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                conditions = []
                params = []
                
                if nivel:
                    conditions.append("nivel = %s")
                    params.append(nivel)
                
                if componente:
                    conditions.append("componente = %s")
                    params.append(componente)
                
                if solo_no_resueltos:
                    conditions.append(
                        "nivel IN ('ERROR','CRITICAL') AND resuelto = FALSE"
                    )
                
                where = ("WHERE " + " AND ".join(conditions)
                        if conditions else "")
                
                cur.execute(f"""
                    SELECT id, timestamp, nivel, componente,
                    funcion, mensaje, whatsapp_id,
                    pedido_id, resuelto, duracion_ms
                    FROM logs_sistema
                    {where}
                    ORDER BY timestamp DESC
                    LIMIT %s OFFSET %s
                """, params + [limite, offset])
                
                return cur.fetchall()
    except Exception:
        return []


def contar_logs(nivel=None, componente=None, solo_no_resueltos=False):
    """
    Cuenta total de logs para paginación.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                conditions = []
                params = []
                
                if nivel:
                    conditions.append("nivel = %s")
                    params.append(nivel)
                
                if componente:
                    conditions.append("componente = %s")
                    params.append(componente)
                
                if solo_no_resueltos:
                    conditions.append(
                        "nivel IN ('ERROR','CRITICAL') AND resuelto = FALSE"
                    )
                
                where = ("WHERE " + " AND ".join(conditions)
                        if conditions else "")
                
                cur.execute(f"SELECT COUNT(*) FROM logs_sistema {where}", params)
                return cur.fetchone()[0]
    except Exception:
        return 0


def marcar_log_resuelto(log_id: int):
    """Marca un log como resuelto."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE logs_sistema
                    SET resuelto = TRUE, resuelto_en = NOW()
                    WHERE id = %s
                """, (log_id,))
                conn.commit()
    except Exception:
        pass


def resumen_errores_hoy():
    """KPIs para el dashboard."""
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE nivel='ERROR' AND timestamp > NOW()-INTERVAL '24 hours') AS errores_24h,
                        COUNT(*) FILTER (WHERE nivel='CRITICAL' AND timestamp > NOW()-INTERVAL '24 hours') AS criticos_24h,
                        COUNT(*) FILTER (WHERE nivel IN ('ERROR','CRITICAL') AND resuelto=FALSE) AS errores_pendientes,
                        COUNT(*) FILTER (WHERE nivel='WARNING' AND timestamp > NOW()-INTERVAL '24 hours') AS warnings_24h,
                        MAX(timestamp) FILTER (WHERE nivel='ERROR') AS ultimo_error
                    FROM logs_sistema
                """)
                return cur.fetchone()
    except Exception:
        return {
            'errores_24h': 0,
            'criticos_24h': 0,
            'errores_pendientes': 0,
            'warnings_24h': 0,
            'ultimo_error': None
        }
```

---

## PARTE 3 - APIs FLASK SIN DUPLICAR CÓDIGO

### 3A. Rutas en app.py

```python
# AGREGAR a bot_empanadas/app.py

# ──── SISTEMA DE LOGS ────────────────────────────
@app.route('/api/logs', methods=['GET'])
@require_admin
def api_logs():
    """
    GET /api/logs?nivel=ERROR&componente=flask&limite=50&offset=0&pendientes=true
    """
    nivel = request.args.get('nivel')
    componente = request.args.get('componente')
    limite = int(request.args.get('limite', 100))
    offset = int(request.args.get('offset', 0))
    pendientes = request.args.get('pendientes') == 'true'
    
    # Validar límite (max 500)
    limite = min(limite, 500)
    
    logs = db.obtener_logs(nivel, componente, limite, offset, pendientes)
    total = db.contar_logs(nivel, componente, pendientes)
    
    return jsonify({
        'logs': [dict(l) for l in logs],
        'total': total,
        'limit': limite,
        'offset': offset,
        'pages': (total + limite - 1) // limite
    })


@app.route('/api/logs/resumen', methods=['GET'])
@require_admin
def api_logs_resumen():
    """GET /api/logs/resumen - KPIs de salud del sistema"""
    return jsonify(dict(db.resumen_errores_hoy()))


@app.route('/api/logs/<int:log_id>/resolver', methods=['PATCH'])
@require_admin
def resolver_log(log_id):
    """PATCH /api/logs/123/resolver"""
    db.marcar_log_resuelto(log_id)
    return jsonify({'ok': True})


@app.route('/api/logs/limpiar', methods=['POST'])
@require_admin
def limpiar_logs():
    """POST /api/logs/limpiar - Ejecutar limpiar_logs_antiguos()"""
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT limpiar_logs_antiguos()")
                conn.commit()
        return jsonify({'ok': True, 'mensaje': 'Logs antiguos eliminados'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ──── ENDPOINT INTERNO PARA LOGS DE BAILEYS ────────────────────────────
@app.route('/interno/log', methods=['POST'])
def recibir_log_externo():
    """
    POST /interno/log
    Recibe logs de Baileys (Node.js) y los guarda en PostgreSQL.
    Solo aceptar desde localhost.
    """
    # Solo aceptar desde localhost
    if request.remote_addr not in ('127.0.0.1', '::1', 'localhost'):
        return '', 403
    
    data = request.get_json(silent=True)
    if not data:
        return '', 400
    
    db.insertar_log(
        nivel=data.get('nivel', 'INFO'),
        componente=data.get('componente', 'baileys'),
        funcion=data.get('funcion', 'unknown'),
        mensaje=data.get('mensaje', '')[:500],
        detalle=data.get('detalle'),
        whatsapp_id=data.get('whatsapp_id'),
        pedido_id=data.get('pedido_id'),
        ip_origen=data.get('ip_origen'),
        duracion_ms=data.get('duracion_ms'),
    )
    
    return '', 204
```

---

## PARTE 4 - SQL: TABLA LOGS_SISTEMA

```sql
-- EJECUTAR EN psql COMO SUPERUSER

CREATE TABLE IF NOT EXISTS logs_sistema (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    nivel VARCHAR(10) CHECK (nivel IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL')),
    componente VARCHAR(30) CHECK (componente IN (
        'flask','bot','voice','db','baileys','payments','backup','scheduler','n8n'
    )),
    funcion VARCHAR(100),
    mensaje TEXT NOT NULL,
    detalle TEXT,
    whatsapp_id VARCHAR(30),
    pedido_id INTEGER,
    ip_origen VARCHAR(45),
    duracion_ms INTEGER,
    resuelto BOOLEAN DEFAULT FALSE,
    resuelto_en TIMESTAMP
);

-- Índices para consultas rápidas en el dashboard
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs_sistema(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_logs_nivel ON logs_sistema(nivel);
CREATE INDEX IF NOT EXISTS idx_logs_componente ON logs_sistema(componente);
CREATE INDEX IF NOT EXISTS idx_logs_resuelto ON logs_sistema(resuelto);

-- Índice compuesto para filtro común (nivel + resuelto)
CREATE INDEX IF NOT EXISTS idx_logs_nivel_resuelto 
ON logs_sistema(nivel, resuelto) WHERE nivel IN ('ERROR', 'CRITICAL');

-- Vista para dashboard (solo errores no resueltos)
CREATE OR REPLACE VIEW errores_activos AS
SELECT id, timestamp, nivel, componente, funcion,
       mensaje, whatsapp_id, pedido_id, resuelto
FROM logs_sistema
WHERE nivel IN ('ERROR','CRITICAL')
AND resuelto = FALSE
ORDER BY timestamp DESC;

-- Función para limpiar logs viejos (ejecutar mensualmente)
CREATE OR REPLACE FUNCTION limpiar_logs_antiguos()
RETURNS void AS $$
BEGIN
    -- Conservar: todos los ERROR/CRITICAL indefinidamente
    -- Eliminar: DEBUG/INFO/WARNING de más de 30 días
    DELETE FROM logs_sistema
    WHERE nivel IN ('DEBUG','INFO','WARNING')
    AND timestamp < NOW() - INTERVAL '30 days';
    
    -- Eliminar: errores resueltos de más de 90 días
    DELETE FROM logs_sistema
    WHERE nivel IN ('ERROR','CRITICAL')
    AND resuelto = TRUE
    AND resuelto_en < NOW() - INTERVAL '90 days';
END;
$$ LANGUAGE plpgsql;
```

---

## PARTE 5 - DASHBOARD ADMIN CON PAGINACIÓN REAL

### 5A. HTML en admin.html

```html
<!-- AGREGAR en sidebar (después de otros nav-items) -->
<div class="nav-item" onclick="show('sistema',this)">
    <span class="nav-dot" style="background:#E24B4A"></span>
    Sistema
</div>

<!-- AGREGAR en main content area (después de sección inventario) -->
<div class="section" id="s-sistema" style="display:none">
    <!-- KPIs DE SALUD -->
    <div class="kpi-grid" id="kpi-sistema">
        <!-- Cargado dinámicamente por cargarSistema() -->
    </div>
    
    <!-- BANNER DE ALERTA si hay críticos -->
    <div id="banner-critico" style="display:none" class="alert alert-danger">
        <strong>⚠️ CRÍTICO:</strong> Hay errores críticos sin resolver. Revisar inmediatamente.
    </div>
    
    <!-- FILTROS -->
    <div class="card" style="margin: 20px 0;">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px;">
            <select id="filtro-nivel" onchange="cargarLogs()">
                <option value="">Todos los niveles</option>
                <option value="CRITICAL">CRITICAL</option>
                <option value="ERROR">ERROR</option>
                <option value="WARNING">WARNING</option>
                <option value="INFO">INFO</option>
                <option value="DEBUG">DEBUG</option>
            </select>
            
            <select id="filtro-componente" onchange="cargarLogs()">
                <option value="">Todos los componentes</option>
                <option value="flask">Flask</option>
                <option value="bot">Bot</option>
                <option value="voice">Voice</option>
                <option value="db">Base de datos</option>
                <option value="baileys">Baileys/WhatsApp</option>
                <option value="payments">Pagos</option>
                <option value="backup">Backups</option>
            </select>
            
            <input type="text" id="buscar-logs" placeholder="Buscar en mensaje..." 
                   onkeyup="cargarLogs()" style="padding: 8px;">
            
            <label style="display: flex; align-items: center; gap: 5px;">
                <input type="checkbox" id="solo-pendientes" onchange="cargarLogs()">
                Solo sin resolver
            </label>
        </div>
        
        <div style="margin-top: 10px; display: flex; gap: 10px;">
            <button onclick="cargarLogs()" class="btn btn-primary">Refrescar</button>
            <button onclick="limpiarLogs()" class="btn btn-danger">Limpiar antiguos</button>
            <button onclick="exportarLogs()" class="btn btn-secondary">Exportar CSV</button>
        </div>
    </div>
    
    <!-- TABLA DE LOGS -->
    <table class="tbl" id="tabla-logs">
        <thead>
            <tr>
                <th>Fecha</th>
                <th>Nivel</th>
                <th>Componente</th>
                <th>Función</th>
                <th>Mensaje</th>
                <th>Cliente</th>
                <th>ms</th>
                <th>Estado</th>
            </tr>
        </thead>
        <tbody id="tbody-logs">
            <tr><td colspan="8" style="text-align:center; padding: 20px; color: #999;">Cargando...</td></tr>
        </tbody>
    </table>
    
    <!-- PAGINACIÓN -->
    <div id="paginacion-logs" style="margin-top: 20px; text-align: center;"></div>
</div>
```

### 5B. JavaScript en admin.html

```javascript
// ──── SISTEMA DE LOGS ────────────────────────────
let logsPagina = 1;
const logsParPagina = 50;

async function cargarSistema() {
    const resumen = await fetch('/api/logs/resumen').then(r => r.json());
    
    const kpiHtml = `
        <div class="kpi">
            <div class="kpi-label">Errores 24h</div>
            <div class="kpi-val ${resumen.errores_24h > 0 ? 'kpi-down' : ''}">${resumen.errores_24h}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Críticos 24h</div>
            <div class="kpi-val ${resumen.criticos_24h > 0 ? 'kpi-down' : ''}">${resumen.criticos_24h}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Sin resolver</div>
            <div class="kpi-val ${resumen.errores_pendientes > 0 ? 'kpi-down' : ''}">${resumen.errores_pendientes}</div>
        </div>
        <div class="kpi">
            <div class="kpi-label">Warnings 24h</div>
            <div class="kpi-val">${resumen.warnings_24h}</div>
        </div>
    `;
    
    document.getElementById('kpi-sistema').innerHTML = kpiHtml;
    
    // Mostrar/ocultar banner si hay críticos
    if (resumen.criticos_24h > 0) {
        document.getElementById('banner-critico').style.display = 'block';
    } else {
        document.getElementById('banner-critico').style.display = 'none';
    }
    
    await cargarLogs();
}

async function cargarLogs() {
    const nivel = document.getElementById('filtro-nivel').value;
    const componente = document.getElementById('filtro-componente').value;
    const pendientes = document.getElementById('solo-pendientes').checked;
    const buscar = document.getElementById('buscar-logs').value;
    
    const offset = (logsPagina - 1) * logsParPagina;
    
    const params = new URLSearchParams();
    if (nivel) params.set('nivel', nivel);
    if (componente) params.set('componente', componente);
    if (pendientes) params.set('pendientes', 'true');
    params.set('limite', logsParPagina);
    params.set('offset', offset);
    
    const response = await fetch(`/api/logs?${params}`);
    const data = await response.json();
    
    const COLORES = {
        CRITICAL: 'badge-red', ERROR: 'badge-red',
        WARNING: 'badge-amber', INFO: 'badge-blue',
        DEBUG: 'badge-gray'
    };
    
    // Filtrar por buscar (cliente-side)
    let logs = data.logs;
    if (buscar) {
        logs = logs.filter(l => 
            l.mensaje.toLowerCase().includes(buscar.toLowerCase())
        );
    }
    
    const tbodyHtml = logs.map(l => `
        <tr ${l.nivel === 'CRITICAL' ? 'style="background: rgba(255,0,0,0.05)"' : ''}>
            <td style="white-space:nowrap;font-size:11px">
                ${new Date(l.timestamp).toLocaleString('es-MX')}
            </td>
            <td><span class="badge ${COLORES[l.nivel] || ''}">${l.nivel}</span></td>
            <td><code style="font-size:11px">${l.componente}</code></td>
            <td style="font-size:11px;color:#666">${l.funcion || '-'}</td>
            <td style="font-size:11px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                title="${l.mensaje}">
                ${l.mensaje}
            </td>
            <td style="font-size:10px">${l.whatsapp_id || '-'}</td>
            <td style="font-size:10px">${l.duracion_ms || '-'}</td>
            <td>
                ${l.resuelto
                    ? '<span class="badge badge-green">✓ Resuelto</span>'
                    : (l.nivel === 'ERROR' || l.nivel === 'CRITICAL')
                        ? `<button class="btn btn-sm btn-success" onclick="resolverLog(${l.id})">Resolver</button>`
                        : '-'
                }
            </td>
        </tr>
    `).join('');
    
    document.getElementById('tbody-logs').innerHTML = tbodyHtml || 
        '<tr><td colspan="8" style="text-align:center; padding: 20px; color: #999;">Sin registros</td></tr>';
    
    // Paginación
    const totalPages = Math.ceil(data.total / logsParPagina);
    const paginacionHtml = `
        <div style="display: flex; gap: 5px; justify-content: center; align-items: center;">
            ${logsPagina > 1 ? `<button class="btn btn-sm" onclick="irPagina(1)">« Primera</button>` : ''}
            ${logsPagina > 1 ? `<button class="btn btn-sm" onclick="irPagina(${logsPagina - 1})">← Anterior</button>` : ''}
            
            <span style="padding: 0 15px; font-size: 14px;">
                Página <strong>${logsPagina}</strong> de <strong>${totalPages}</strong>
                (${data.total} registros totales)
            </span>
            
            ${logsPagina < totalPages ? `<button class="btn btn-sm" onclick="irPagina(${logsPagina + 1})">Siguiente →</button>` : ''}
            ${logsPagina < totalPages ? `<button class="btn btn-sm" onclick="irPagina(${totalPages})">Última »</button>` : ''}
        </div>
    `;
    
    document.getElementById('paginacion-logs').innerHTML = paginacionHtml;
}

function irPagina(pagina) {
    logsPagina = pagina;
    cargarLogs();
    document.querySelector('#tabla-logs').scrollIntoView({ behavior: 'smooth' });
}

async function resolverLog(id) {
    await fetch(`/api/logs/${id}/resolver`, { method: 'PATCH' });
    await cargarLogs();
}

async function limpiarLogs() {
    if (!confirm('¿Eliminar logs INFO/WARNING/DEBUG de más de 30 días?')) return;
    
    await fetch('/api/logs/limpiar', { method: 'POST' });
    alert('Limpieza completada');
    
    logsPagina = 1;
    await cargarLogs();
}

function exportarLogs() {
    alert('Función de exportar CSV en desarrollo...');
}

// Auto-refresh cada 2 minutos (solo cuando visibles)
let sistemaInterval = null;

function onSistemaMostrado() {
    cargarSistema();
    sistemaInterval = setInterval(cargarSistema, 120000);
}

function onSistemaOculto() {
    clearInterval(sistemaInterval);
}

// Integrar con función show() existente
// Modificar la función show() en admin.html para llamar:
// if(seccion === 'sistema') onSistemaMostrado(); else onSistemaOculto();
```

---

## 📋 CHECKLIST DE IMPLEMENTACIÓN

### DÍA 1 - Base de Datos (30 min)
- [ ] Ejecutar SQL de CREATE TABLE logs_sistema
- [ ] Verificar índices e indices existentes
- [ ] Testear inserción manual

### DÍA 1 - Logger (45 min)
- [ ] Crear logging_handlers.py (sin imports circulares)
- [ ] Crear logger.py refactorizado
- [ ] Agregar funciones a db.py

### DÍA 2 - Backup (30 min)
- [ ] Agregar funciones Get-OneDrivePath, Copy-ToOneDrive, Clean-OneDrive a backup_postgres.ps1
- [ ] Integrar en flujo principal
- [ ] Testear copia a OneDrive manualmente

### DÍA 2 - Flask (30 min)
- [ ] Agregar rutas /api/logs, /api/logs/resumen, /interno/log a app.py
- [ ] Testear con curl/Postman
- [ ] Verificar que datos llegan a BD

### DÍA 3 - Admin UI (60 min)
- [ ] Agregar nav-item y sección HTML
- [ ] Agregar JavaScript con paginación
- [ ] Testear filtros, búsqueda, paginación

### DÍA 3 - Integración (30 min)
- [ ] Importar logger en app.py, bot.py, voice.py, db.py
- [ ] Testear error en ruta Flask → aparece en logs_sistema
- [ ] Testear error en bot → aparece en logs_sistema

---

## 🎯 BENEFICIOS DE LA REFACTORIZACIÓN

✅ **Sin imports circulares** - logging_handlers.py es independiente  
✅ **Sin bloqueos** - OneDrive copy es asincrónico, no bloquea Task Scheduler  
✅ **Rate-limited** - Evita spam de 1000s logs/min  
✅ **Paginación real** - Navega 1000s de logs sin cargar todos a memoria  
✅ **Validación cuota** - Antes de copiar verifica >500MB libres  
✅ **Compatible 100%** - Extiende backup_postgres.ps1 sin reescribir  
✅ **Reversible** - Si algo falla, revertir Copy-ToOneDrive no rompe nada  

---

**¿LISTO PARA EMPEZAR?**
Recomendación: Implementar en orden día 1 → día 2 → día 3.
Cada día toma ~1.5 horas y puede testearse independientemente.
