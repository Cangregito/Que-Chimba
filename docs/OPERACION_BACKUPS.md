# Operacion de Backups y Restore (Que Chimba)

## Objetivo

Este modulo protege PostgreSQL sin cambiar la logica funcional del sistema.

Incluye:

- Backup automatico con hash SHA-256
- Retencion automatica por dias y cantidad
- Verificacion de restore en base temporal
- Logs operativos en disco
- Alerta por webhook (opcional)
- Replica espejo de backups (opcional)
- Simulacro DR end-to-end
- Diagnostico de readiness (pre-flight)
- Alerta opcional directa a WhatsApp (via bridge)

## Scripts

- scripts/ops/backup_postgres.ps1
- scripts/ops/verify_restore_postgres.ps1
- scripts/ops/register_backup_tasks.ps1
- scripts/ops/run_dr_drill.ps1
- scripts/ops/check_backup_readiness.ps1
- scripts/ops/configure_ops_automation.ps1

## Diagnostico inicial (recomendado)

Antes de programar tareas, valida prerequisitos:

```powershell
.\scripts\ops\check_backup_readiness.ps1 -DbHost localhost -DbPort 5432 -DbName que_chimba -DbUser postgres -MirrorRoot "C:\Backups\QueChimbaMirror" -AlertWebhookUrl $env:OPS_ALERT_WEBHOOK
```

El script valida:

- pg_dump, psql y schtasks disponibles
- permisos de escritura en backup/log/mirror
- presencia de DB_PASSWORD
- conectividad real a PostgreSQL
- webhook de alertas (si lo configuras)

## Configuracion automatica recomendada

Este comando deja todo listo en una sola pasada:

```powershell
.\scripts\ops\configure_ops_automation.ps1
```

Que configura automaticamente:

- mirror en OneDrive (`<OneDrive>\\QueChimba\\backups_mirror`)
- tareas programadas (backup diario + verify semanal)
- alertas a WhatsApp si existe `WHATSAPP_ADMIN`
- alertas por webhook si pasas `-AlertWebhookUrl`

Detalle tecnico:

- La ruta de mirror se guarda en variable de entorno de usuario `OPS_MIRROR_ROOT` para evitar problemas de acentos/rutas en tareas programadas.

Ejemplo con webhook:

```powershell
.\scripts\ops\configure_ops_automation.ps1 -AlertWebhookUrl "https://tu-webhook"
```

Nota de WhatsApp:

- Las alertas a WhatsApp no son directas por numero; se envian al bridge (`/api/send-text`) y este entrega el mensaje.
- Puedes usar cualquier numero admin (recomendado), no el mismo numero del bot.

## Variables recomendadas

PowerShell:

```powershell
$env:DB_PASSWORD = "tu_password"
```

Importante para tareas programadas:

- Si quieres que funcionen en ejecucion nocturna sin terminal abierta, define DB_PASSWORD de forma persistente para tu usuario (no solo en sesion actual).

```powershell
setx DB_PASSWORD "tu_password"
```

Despues de `setx`, abre una terminal nueva para validar variables.

Opcional para alertas:

```powershell
$env:OPS_ALERT_WEBHOOK = "https://tu-webhook"
```

## Ejecucion manual

Backup:

```powershell
.\scripts\ops\backup_postgres.ps1 -DbHost localhost -DbPort 5432 -DbName que_chimba -DbUser postgres -MirrorRoot "C:\Backups\QueChimbaMirror" -AlertWebhookUrl $env:OPS_ALERT_WEBHOOK
```

Verificacion de restore:

```powershell
.\scripts\ops\verify_restore_postgres.ps1 -DbHost localhost -DbPort 5432 -DbUser postgres -AlertWebhookUrl $env:OPS_ALERT_WEBHOOK
```

Simulacro DR completo:

```powershell
.\scripts\ops\run_dr_drill.ps1 -DbHost localhost -DbPort 5432 -DbName que_chimba -DbUser postgres -MirrorRoot "C:\Backups\QueChimbaMirror" -AlertWebhookUrl $env:OPS_ALERT_WEBHOOK
```

## Programacion automatica

Ejemplo con argumentos de produccion local:

```powershell
.\scripts\ops\register_backup_tasks.ps1 `
  -TaskPrefix QueChimba `
  -BackupTime 02:00 `
  -VerifyTime 03:00 `
  -VerifyDay SUN `
  -BackupArguments "-DbHost localhost -DbPort 5432 -DbName que_chimba -DbUser postgres -MirrorRoot 'C:\Backups\QueChimbaMirror' -AlertWebhookUrl '$env:OPS_ALERT_WEBHOOK'" `
  -VerifyArguments "-DbHost localhost -DbPort 5432 -DbUser postgres -AlertWebhookUrl '$env:OPS_ALERT_WEBHOOK'"
```

## Salidas esperadas

- backups/postgres/*.zip
- backups/postgres/*.json
- logs/ops/backup-postgres-YYYY-MM.log
- logs/ops/verify-restore-postgres-YYYY-MM.log

## Checklist mensual

- Ejecutar run_dr_drill.ps1 manualmente al menos 1 vez al mes
- Confirmar existencia de backup del dia y hash
- Confirmar que la tarea de backup se ejecuto sin error
- Confirmar que la tarea de verify se ejecuto sin error
- Verificar espacio libre en disco de backup y mirror
