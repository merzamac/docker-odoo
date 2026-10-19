# Decisiones de Arquitectura — Módulo `payment_request`

## 1. Concurrencia y Bloqueo Pesimista (Row-Level Locking)

Para evitar que dos aprobadores procesen una solicitud simultáneamente en navegadores distintos, se descartó el chequeo condicional simple en Python (`if state == 'sent'`), ya que en entornos multi-worker ambas transacciones leen el mismo estado en memoria antes del commit (condición TOCTOU).

Se implementó un bloqueo pesimista directo en el motor de base de datos:

```sql
SELECT id, state FROM payment_request WHERE id = %s FOR UPDATE NOWAIT;
```

Esto garantiza que la primera transacción adquiere un cerrojo exclusivo sobre la fila en PostgreSQL; cualquier petición paralela es rechazada de inmediato (`NOWAIT` → `psycopg2.OperationalError` → mensaje amigable al usuario) sin esperas ni inconsistencias. El estado de la fila se re-verifica bajo el bloqueo antes de aprobar, lo que también bloquea la doble aprobación secuencial.

## 2. Gestión Bimoneda (USD / VES)

El negocio factura habitualmente en dólares pero liquida en bolívares desde cuentas bancarias locales. La solicitud preserva la moneda del pasivo original (`currency_id`). Al pagar:

1. El wizard detecta la moneda efectiva del pago: la del diario seleccionado (`journal_id.currency_id`) o, si el diario está en moneda de compañía, la de la compañía.
2. Aplica `currency_id._convert(amount, destino, company, payment_date)`, es decir, la tasa oficial de la **fecha de pago**.
3. El asiento contable en `account.payment` se crea y contabiliza en la moneda del diario a esa tasa.

## 3. Integridad Transaccional

La confirmación de la solicitud a estado `paid` está acoplada atómicamente a la validación del pago en `account.payment`. El estado solo cambia **después** de `action_post()` exitoso; si la creación o contabilización del pago falla (período cerrado, error de cuentas), la excepción revierte la transacción SQL completa (ROLLBACK), evitando solicitudes huérfanas en estado pagado y pagos huérfanos.

## 4. Multi-Compañía

Tanto los niveles de aprobación como las solicitudes poseen `company_id`. Se configuraron reglas de registro (`ir.rule`) globales con el dominio `[('company_id', 'in', company_ids)]`, garantizando aislamiento absoluto entre razones sociales. Sobre esas reglas globales se suman (conector OR) las reglas por grupo: el solicitante solo ve las suyas; aprobadores y tesorería ven todas las de su compañía.
