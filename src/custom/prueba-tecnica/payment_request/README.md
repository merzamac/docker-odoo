# Solicitudes de Pago con Aprobación (`payment_request`)

Módulo desarrollado para Odoo 18.0 que formaliza el flujo de solicitudes de desembolso para proveedores, reemplazando la gestión informal de mensajes y aportando control financiero y trazabilidad contable.

## Tramos Completados

- **Tramo A:** Modelo base, secuencia `SP/2026/0001`, inmutabilidad post-envío, restricción de montos positivos y reglas de registro (solicitante solo ve sus registros y no puede aprobar, ni desde el botón ni llamando al método).
- **Tramo B:** Niveles de aprobación configurables (`payment.approval.level`), actividades automáticas al enviar, wizard de rechazo con motivo publicado en el chatter, wizard de pago con `account.payment` vinculado y reporte QWeb PDF con aprobador y fecha.
- **Tramo C:** Conversión de divisas (USD a VES) con la tasa de la fecha de pago, aislamiento multi-compañía, atomicidad transaccional (si el pago falla no queda pagada) y bloqueo pesimista en PostgreSQL contra concurrencia.

## Supuestos y Preguntas al Cliente (Carolina Méndez)

### Preguntas para el Cliente

1. **Umbrales monetarios:** ¿Cuál es el monto exacto a partir del cual un pago se clasifica como "grande" para escalar a Gerencia?
2. **Facturas vs Anticipos:** ¿Las solicitudes de pago deben cruzarse con facturas de proveedor ya cargadas en Odoo, o son pagos anticipados/directos a cuenta?
3. **Tasa de Cambio:** ¿Para pagos en bolívares de solicitudes en dólares se debe utilizar la tasa oficial del día de Odoo (BCV) o tesorería debe ingresar manualmente una tasa pactada?

### Supuestos Asumidos

1. **Configuración de Niveles:** Se implementó un catálogo dinámico (`payment.approval.level`) para que administración defina los umbrales monetarios por compañía sin requerir cambios de código. Si no hay nivel aplicable, el sistema asigna al primer aprobador disponible de la compañía.
2. **Pagos Directos:** Los pagos se generan como egresos directos de tesorería (`account.payment` tipo `supplier`/`outbound`).
3. **Conversión Cambiaria:** Se utiliza la tasa oficial registrada en Odoo (`res.currency._convert`) a la fecha indicada en el pago.
4. **Grupos:** El grupo "Solicitante" se otorga manualmente a los empleados desde Configuración → Usuarios; los grupos "Aprobador" y "Tesorería" implican los inferiores.
5. **Rechazo:** El rechazo lo realizan Aprobador/Tesorería (no el solicitante), con motivo obligatorio publicado en el chatter.

## Limitaciones

- La aprobación concurrente se protege con `SELECT ... FOR UPDATE NOWAIT`; el test automatizado cubre la doble aprobación secuencial, pero la prueba real con dos procesos simultáneos no es automatizable en `TransactionCase` (requiere dos transacciones aisladas reales).
- El cruce con facturas de proveedor queda pendiente de respuesta al cliente (pregunta 2).
- Si la compañía no tiene ningún usuario en el grupo "Aprobador", la solicitud se envía sin aprobador asignado y cualquier aprobador podrá aprobarla después.

## Cómo Probarlo

```bash
./odoo test -d prueba_limpia -m payment_request
```

Prueba final combinada de los cuatro módulos del examen:

```bash
./odoo test -d prueba_limpia -m shop_integration_api,fleet_inspection,sale_commission,payment_request
```
