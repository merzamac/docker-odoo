# AI_LOG — payment_request

## Herramientas

- Claude 3.5 Sonnet

## Prompts clave (3 a 5)

1. "Estructura de un wizard en Odoo 18 para crear un account.payment outbound y vincularlo al modelo origen."
   - Entregó la estructura básica del TransientModel. Adapté el cálculo de conversión bimoneda con `_convert()`.
2. "Sintaxis para bloqueo pesimista en PostgreSQL con Odoo ORM evitando esperas infinitas."
   - Proveyó la sintaxis `FOR UPDATE NOWAIT`. Implementé la captura de `psycopg2.OperationalError` para retornar un mensaje amigable al usuario.
3. "Plantilla de reporte QWeb PDF en Odoo 18 mostrando firmas y campos relacionales."
   - Generó el XML base; adapté los nodos para mostrar al aprobador y la fecha exacta de aprobación.

## Lo que la IA hizo mal

- Intentó usar `attrs="{'invisible': ...}"` en la vista del formulario. En Odoo 18 se utilizan expresiones directas en `invisible="..."`. Se corrigió manualmente.
- Usó la etiqueta deprecada `<tree>` en lugar de `<list>`.

## Lo que escribiste tú sin IA

- El diseño funcional de preguntas y supuestos para el cliente Carolina Méndez.
- La lógica de precedencia en la selección del nivel de aprobación según montos por compañía.

## Verificación Final de Cumplimiento

| Requerimiento del PDF | Dónde se resuelve | Garantía |
|---|---|---|
| Secuencia SP/2026/0001 | `data/ir_sequence_data.xml` + `create()` | Cumplido |
| Inmutabilidad post-envío | `write()` en modelo + readonly en XML | Cumplido |
| Monto ≤ 0 bloqueado | `@api.constrains('amount')` | Cumplido |
| Solicitante solo ve las suyas | `ir.rule` con `applicant_id = user.id` | Cumplido |
| Solicitante no puede aprobar | Validación en `action_approve()` + grupos | Cumplido |
| Aprobación configurable | Modelo `payment.approval.level` | Cumplido |
| Actividad al enviar | `activity_schedule()` en `action_send()` | Cumplido |
| Rechazo con motivo en chatter | Wizard `payment.request.reject.wizard` | Cumplido |
| No pagar dos veces | Chequeo estricto en wizard de pago + test | Cumplido |
| Reporte PDF con aprobador | `report/payment_request_report.xml` | Cumplido |
| Conversión USD → VES | `_convert()` en wizard de pago | Cumplido |
| Concurrencia resuelta | `SELECT ... FOR UPDATE NOWAIT` en SQL | Cumplido |
| Aislamiento Multi-Compañía | Reglas de registro con `company_ids` | Cumplido |
| Pruebas Automatizadas | `tests/test_payment_request.py` (13 tests) | Cumplido |
| Documentación exigida | `README.md`, `ARCHITECTURE.md`, `AI_LOG.md` | Cumplido |
