# Tecnificacion de Venta de Empanadas

## Metodologia de Desarrollo

Se adopta Scrum ligero para este proyecto por tres razones:

1. Entregas iterativas por sprint permiten validar rapido con el cliente (bot, paneles, pagos, landing).
2. Prioriza backlog por valor de negocio y riesgo tecnico (WhatsApp, pagos, inventario, seguridad).
3. Facilita revisiones frecuentes y ajustes de alcance sin frenar la operacion.

Cadencia sugerida:

- Sprint semanal
- Planeacion corta
- Daily de 10-15 min
- Review con demo funcional
- Retro con acciones de mejora

## Roles del Sistema

- Administrador
- Cocina
- Repartidor
- Cliente

## Historias de Usuario

| ID | Usuario | Historia | Criterios de Aceptacion (CA) |
| --- | --- | --- | --- |
| HU-01 | Cliente | Como cliente quiero pedir por WhatsApp para comprar sin instalar apps. | CA1: El bot acepta texto y audio. CA2: Registra pedido en BD. CA3: Devuelve confirmacion de pedido. |
| HU-02 | Cliente | Como cliente quiero recibir respuestas con voz y texto para entender mejor el flujo. | CA1: El sistema responde con audio cuando el turno es de audio. CA2: El mismo turno incluye texto guia. |
| HU-03 | Cliente | Como cliente quiero que mi sesion expire automaticamente para proteger mi privacidad. | CA1: La sesion expira a 5 dias. CA2: Sesiones vencidas se limpian al procesar nuevos mensajes. |
| HU-04 | Administrador | Como admin quiero ver KPIs diarios, mensuales y anuales para tomar decisiones. | CA1: Panel muestra ventas de hoy, mes y ano. CA2: Existe refresco manual. CA3: Existe refresco automatico por intervalo. |
| HU-05 | Cocina | Como cocina quiero ver pedidos en cola y mover estados para operar rapido. | CA1: Tablero muestra recibido/en preparacion/listo. CA2: Permite actualizar estado. CA3: Permite imprimir QR de pedido. |
| HU-06 | Repartidor | Como repartidor quiero validar entregas por codigo para evitar errores. | CA1: Puede abrir pedido listo. CA2: Puede confirmar entrega con codigo. CA3: Registra resultado en BD. |
| HU-07 | Repartidor | Como repartidor quiero escanear QR del pedido para localizarlo mas rapido. | CA1: Existe accion de escaneo QR. CA2: El QR identifica pedido. CA3: Abre el cuadro de confirmacion del pedido detectado. |
| HU-08 | Administrador | Como admin quiero controlar inventario para evitar quiebres de stock. | CA1: Existe stock actual y stock minimo. CA2: Se registran movimientos de inventario. CA3: Existen alertas de bajo stock. |
| HU-09 | Administrador | Como admin quiero registrar proveedores para compras recurrentes. | CA1: Cada insumo puede asociarse a proveedor. CA2: Se registra telefono del proveedor. |
| HU-10 | Cliente | Como cliente quiero pagar con tarjeta para comprar sin efectivo. | CA1: Existe integracion con MercadoPago. CA2: Se persiste estatus de pago. CA3: Se notifica resultado. |
| HU-11 | Administrador | Como admin quiero corte por efectivo y tarjeta para cierre diario. | CA1: Existe reporte de total efectivo. CA2: Existe reporte de total tarjeta. CA3: Existe total general. |
| HU-12 | Marketing | Como marketing quiero que landing y redes me lleven a WhatsApp para mejorar conversion. | CA1: Botones de redes dirigen a WhatsApp. CA2: CTA principal dirige a WhatsApp. |

## Definicion de Hecho (DoD)

- Codigo versionado y revisado.
- Prueba de regresion principal en verde.
- Sin errores de sintaxis en modulos tocados.
- Evidencia de cumplimiento actualizada en README o documento de requisitos.
