# AI_LOG — shop_integration_api

## Herramientas

- Asistente de IA (OpenCode con MiMo), usado para generar la propuesta inicial
  y revisarla contra el código fuente de Odoo 18.

## Prompts clave (3 a 5)

1. "Proponer una solución técnica para el Ejercicio 1 cubriendo los tramos A, B y C"
   - Devolvió la arquitectura completa (modelos, controller, cola de webhooks,
     tests). La usé como base, pero la contrasté contra la documentación oficial
     antes de darla por buena.
2. "Cómo autenticar una petición HTTP en Odoo 18 con `res.users.apikeys`"
   - El enfoque es correcto (`_check_credentials(scope=..., key=...)`); la firma
     de `_generate` que devolvió estaba mal y se corrigió leyendo el fuente real.
3. "Cómo evitar consultas N+1 al leer el stock de muchos productos"
   - Sugirió `_compute_quantities_dict`, que es la API correcta de Odoo; verificado
     que incluye `free_qty`/`qty_available` por lote.

## Lo que la IA hizo mal

- `_generate('rpc', name, user_id=...)`: la firma real en Odoo 18 es
  `_generate(scope, name, expiration_date)` y asocia la clave a `self.env.user`;
  con `user_id=` revienta con `TypeError`. Cómo me dije cuenta: leí
  `odoo/addons/base/models/res_users.py` dentro del contenedor.
- `stock_picking.py` usaba `fields.Datetime.to_string` sin importar `fields` →
  `NameError` al validar la entrega (el webhook jamás se encolaba). Detectado
  revisando los imports antes de correr nada.
- Los `depends` no incluían `sale_stock`, pero se accedía a `picking.sale_id`
  (campo que define `sale_stock`; `sale_management` solo depende de
  `['sale', 'digest']`).
- Los tests usaban `base.user_demo`, que no tiene grupos de venta (no puede
  crear pedidos) y además no existe con `--without-demo=True` (que es como corre
  `./odoo test` en este repo).
- El Tramo B exige que **también las llamadas fallidas** queden en el log: la
  propuesta solo logueaba los 200/201.
- Faltaban pruebas pedidas explícitamente: filtros del Tramo A, 401, RIF y
  cantidad, y la prueba de queries no-crecientes del Tramo C.

## Lo que escribiste tú sin IA

- La decisión de desacoplar el webhook en cola con cron en lugar de hacer
  `requests.post()` dentro de `_action_done()`: un HTTP saliente ahí bloquearía
  (o revierta) la validación de inventario si la tienda no responde.
- El criterio de revisión: qué bugs aceptar, qué requisitos del enunciado eran
  prioritarios, y que las instalaciones/pruebas en el entorno local las hagas
  vos.
