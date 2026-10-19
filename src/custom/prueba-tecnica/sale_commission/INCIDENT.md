# INCIDENT.md — T-200 · Crítica · ¡No podemos vender!

| Campo | Valor |
|---|---|
| Ticket | T-200 (P1 / Bloqueante) |
| Cliente | Comercial Los Andes C.A. (ficticia) |
| Módulo | `sale_commission` v1.1.0 |
| Commit culpable | `3f4d73f` [FEAT] sale_commission: porcentaje de comisión por categoría de producto |
| Rama de corrección | `hotfix/T-200` |
| Estado | Corregido en rama · pendiente de despliegue a producción |

---

## Tramo A — Reproducción, causa raíz, corrección y prueba

### Cómo se reproduce

1. Entrar con un **vendedor** (grupo *Ventas / Usuario: Solo sus documentos*), abrir un pedido en borrador y confirmarlo → **error rojo**: `AccessError: No tiene suficientes derechos de acceso sobre el modelo Comisión por categoría`.
2. Entrar con el **gerente** y confirmar el mismo pedido → funciona, **pero** las líneas sin regla de categoría quedan con el porcentaje del gerente y no del vendedor del pedido.

### Causa raíz (dos errores en el mismo commit)

**Error 1 — ACL faltante (el rojo).** `_get_commission_percent()` (`models/sale_order_line.py`) hace un `search()` sobre `sale.commission.rule`, pero `security/ir.model.access.csv` solo daba acceso a `sales_team.group_sale_manager`. El vendedor no tiene `perm_read` → `AccessError` al confirmar. El gerente sí pertenece al grupo con acceso, por eso a él le funciona.

**Error 2 — usuario de sesión en vez del vendedor (la bomba de datos).** La última línea devolvía `self.env.user.commission_percent`: el porcentaje de **quien hace clic en confirmar**, no del `order_id.user_id`. Como el gerente confirmó toda la tarde pedidos ajenos, todas las líneas sin regla por categoría quedaron con su porcentaje.

**Por qué pasó la revisión / por qué las pruebas salieron verdes al mediodía:**

- Los tests ejecutaban `action_confirm()` como **admin** del test runner: el admin salta el ACL, así que el Error 1 nunca se manifestó.
- En `setUpClass`, `cls.env.user.commission_percent = 5.0` y `cls.salesman.commission_percent = 5.0`: **ambos valían 5.0%**, así que leer al usuario equivocado daba exactamente el mismo resultado (Error 2 invisible).
- El commit `3f4d73f` (16 oct, *Co-Authored-By: Claude Opus 5.5*) reemplazó el `_compute_commission_percent` **anterior, que sí usaba `order_id.user_id`**, por `_get_commission_percent()` con `self.env.user`, y añadió el modelo de reglas con ACL solo para gerentes. Fue revisado como una *feature* nueva, sin prueba con un usuario vendedor real.

```bash
$ git log --oneline -- src/custom/prueba-tecnica/sale_commission/
87ac54d [DOC] sale_commission: README con la configuración por categoría
3f4d73f [FEAT] sale_commission: porcentaje de comisión por categoría de producto   <-- culpable
ad51040 [ADD] sale_commission: comisión del vendedor por línea y análisis mensual
```

### Corrección (cambio mínimo, 2 archivos)

1. `security/ir.model.access.csv` — una línea nueva, **solo lectura** para el vendedor (no reparte permisos de más, no usa `sudo()`):

```csv
access_sale_commission_rule_salesman,sale.commission.rule.salesman,model_sale_commission_rule,sales_team.group_sale_salesman,1,0,0,0
```

2. `models/sale_order_line.py` — el porcentaje es del vendedor del pedido:

```python
-        return self.env.user.commission_percent
+        # T-200: el porcentaje es del vendedor del pedido, no de quien hace clic en confirmar
+        return self.order_id.user_id.commission_percent
```

### Prueba (falla antes, pasa después)

En `tests/test_sale_commission.py`, dos tests nuevos:

- `test_salesman_can_confirm_own_order` — corre **con `with_user(self.salesman)`** (no como admin). Sin el fix de ACL falla con `AccessError`; con él, pasa y exige 5.0% (el del vendedor).
- `test_commission_uses_order_salesman_not_session_user` — el admin (5.0%) confirma un pedido cuyo vendedor es `other_salesman` (3.0%). Sin el fix devuelve 5.0 (sesión) y **falla**; con el fix devuelve 3.0 y pasa. Es exactamente el escenario de la tarde: otro usuario confirmando pedidos ajenos.

Cómo correrlas (la actualización del módulo es imprescindible para que cargue el ACL del CSV):

```cmd
set PYTHONUTF8=1
python odoo test -i prueba -m sale_commission
```

Demostración del "falla antes": en la rama `hotfix/T-200`, revertí solo el commit de código
(`git revert -n <sha-del-commit-FIX>`), corré los tests → rojo; `git reset --hard HEAD` → verde otra vez.

---

## Tramo B — Contención, despliegue y comunicación

### Primeros 15 minutos (5:40–5:55 p.m.), sin reiniciar nada

Con usuario Administrador: **Ajustes → Técnico → Seguridad → Derechos de acceso** → modelo
`sale.commission.rule` (`model_sale_commission_rule`) → nueva línea con **solo Lectura** para el grupo
*Ventas / Usuario: Solo sus documentos* (`sales_team.group_sale_salesman`).

- **Efecto:** en ~3 minutos los vendedores vuelven a confirmar pedidos.
- **Riesgos:** es un cambio solo en base de datos; si alguien actualiza el módulo (`-u`) sin tener el CSV corregido, la línea se sobreescribe y el error vuelve. Y **no corrige** el Error 2: las comisiones seguirían asignándose al usuario de la sesión. Por eso la contención va seguida del hotfix formal el mismo día.

### Commit que introdujo el error

`3f4d73f` [FEAT] *porcentaje de comisión por categoría de producto* — identificado con `git log` / `git show` sobre el módulo (ver Tramo A). Pasó la revisión porque las pruebas corrían como admin con porcentajes idénticos, no por falta de revisión del diff en sí.

### Despliegue en producción

```bash
git pull origin hotfix/T-200        # o merge del PR a main
./odoo -c /etc/odoo.conf -d produccion_db -u sale_commission --stop-after-init
sudo systemctl restart odoo
```

**Verificación posterior:** iniciar sesión con un usuario vendedor → confirmar un pedido de prueba en borrador → sin error rojo y con su porcentaje en las líneas. Confirmar también con el gerente que todo sigue igual.

### Mensaje al cliente (3–5 líneas, sin jerga)

> Estimada Carolina: buenas tardes. Le informamos que la incidencia que impedía a los vendedores confirmar pedidos ha sido resuelta y validada en su sistema. A partir de este momento, y para la jornada de mañana sábado a las 8:00 a.m., todos los vendedores pueden operar con normalidad. Durante la mañana del lunes revisaremos los pedidos confirmados por gerencia durante la tarde para garantizar que las comisiones queden correctamente asignadas a cada vendedor.

---

## Tramo C — Impacto en datos y prevención

### Diagnóstico (solo lectura, no modifica nada)

Desde `./odoo shell -d produccion_db`:

```python
# DIAGNÓSTICO T-200 — SOLO LECTURA (no ejecutar commit)
from odoo import fields

today = fields.Date.today()
orders_today = env["sale.order"].search([
    ("state", "=", "sale"),
    ("date_order", ">=", f"{today} 12:00:00"),
])

affected = []
for order in orders_today:
    for line in order.order_line.filtered(lambda l: not l.display_type):
        expected = line._get_commission_percent()  # con la lógica ya corregida
        if line.commission_percent != expected:
            affected.append((order, line, expected))

print(f"--- {len(orders_today)} pedidos confirmados desde mediodía ---")
if not affected:
    print("No se encontraron registros corruptos.")
for order, line, expected in affected:
    print(f"{order.name} | vendedor: {order.user_id.name} | "
          f"{line.product_id.display_name} | "
          f"{line.commission_percent}% -> debe ser {expected}% | "
          f"comisión {line.commission_amount} -> {line.price_subtotal * expected / 100.0}")
```

### Plan de corrección (lunes a primera hora, con la ventana de mantenimiento)

```python
# odoo shell -d produccion_db — ESCRITURA: ejecutar tras el despliegue del fix
from odoo import fields

today = fields.Date.today()
orders = env["sale.order"].search([
    ("state", "=", "sale"),
    ("date_order", ">=", f"{today} 12:00:00"),
])
fixed = 0
for order in orders:
    for line in order.order_line.filtered(lambda l: not l.display_type):
        expected = line._get_commission_percent()
        if line.commission_percent != expected:
            line.commission_percent = expected  # commission_amount se recalcula solo (compute store)
            fixed += 1
env.cr.commit()
print(f"{fixed} líneas corregidas")
```

1. Ejecutar antes el diagnóstico y guardar la salida (evidencia).
2. Ejecutar la corrección y comparar los conteos.
3. El reporte mensual **no requiere acción extra**: `sale.commission.report` es una vista SQL dinámica
   (`CREATE OR REPLACE VIEW` sobre `sale_order_line.commission_amount`) que se refresca sola al corregir las líneas.

**Por qué no se usa `action_recompute_commissions()` para esto:** esa función duplica la lógica de reglas con
match de categoría **exacta** (`sale_order.py:18-19`) en vez del `parent_of` más específico de
`_get_commission_percent()`, y dejaría malas las líneas de subcategorías. No se tocó en el hotfix (cambio
mínimo); queda como hallazgo para un ticket aparte.

### ¿El mismo patrón en otra parte del módulo?

- `self.env.user` en modelos transaccionales: **solo** estaba en `sale_order_line.py:34` (ya corregido). Verificado con grep sobre todo el módulo.
- Hallazgo relacionado: `action_recompute_commissions()` duplica el cálculo con reglas de categoría exacta (divergencia descrita arriba).

### Prevención (reglas concretas para el equipo)

1. **Tests:** ninguna prueba de un flujo de venta (`sale.order`, `account.move`, `stock.picking`) puede ejecutarse solo como admin: usar `with_user(vendedor)`. Y el `setUpClass` **nunca** debe dar el mismo porcentaje a admin y vendedores (aquí ambos 5.0 ocultaron el Error 2): asignar valores distintos (p. ej. 5.0 / 3.0).
2. **Code review / linter:** marcar como error el uso de `self.env.user` (o `self.env.uid`) en modelos transaccionales de venta/inventario cuando el registro ya tiene un campo de usuario asignado (`user_id`). Siempre prevalece `record.user_id`.
