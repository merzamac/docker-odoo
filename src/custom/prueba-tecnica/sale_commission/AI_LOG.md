# AI_LOG — sale_commission

## Herramientas
- Claude Opus 5.5 — desarrollo original del módulo (según el trailer `Co-Authored-By` del commit `3f4d73f`).
- Asistente de IA en OpenCode (modelo MiMo) — análisis del incidente T-200, correcciones, pruebas y documentación.

## Prompts clave (3 a 5)
1. "Te presento la solución integral y definitiva del ticket T-200… analizar las soluciones y debemos hacer el menor ajuste posible dándole prioridad al flujo de trabajo"
   - Se analizó contra el código real y el git del repo; se corrigieron dos puntos de la solución traída (ver abajo) y se ejecutó el plan mínimo en la rama `hotfix/T-200`.
2. "Necesito que pases todo el módulo de sale_commission a un solo archivo .md"
   - Se generó `sale_commission.md` con los 19 archivos transcrito byte a byte y verificación automática de ida y vuelta.
3. "Debemos hacer commit de este módulo / este módulo también debe llevar AI_LOG.md"
   - Definió el esquema de commits y la plantilla de este archivo.
4. Durante el diagnóstico: "la vista de formulario no está cargando bien" (en el módulo hermano) — el mismo patrón de pedir evidencia (logs, BD, fuente) se usó aquí para confirmar ACL y línea culpable con `git show`.

## Lo que la IA hizo mal
- La solución "definitiva" traída para T-200 incluía **una sola prueba que no detectaba el Error 2**: corría con `with_user(salesman)` y en el `setUpClass` admin y vendedor valían ambos 5.0%, así que con `self.env.user` roto también habría dado 5.0 y el test habría pasado en verde. Cómo se detectó: al contrastar el test propuesto contra `setUpClass` (líneas 14-15) y contra el escenario real (gerente confirmando pedidos ajenos). Se añadió una segunda prueba donde admin (5.0) confirma el pedido de un vendedor con 3.0%.
- El plan de saneamiento propuesto usaba `action_recompute_commissions()`, pero esa función duplica la lógica con match de categoría **exacta** y diverge de `_get_commission_percent()` (`parent_of`) en subcategorías: habría "corregido" dejando líneas malas. Cómo se detectó: lectura de `sale_order.py:18-19` al preparar el Tramo C. Se reemplazó por un plan que usa `_get_commission_percent()` directo, sin tocar la función en el hotfix.
- El propio bug venía de un commit co-autorado con IA (`3f4d73f`, Claude): reemplazó un compute correcto (`order_id.user_id`) por `self.env.user` y añadió el modelo de reglas con ACL solo para gerentes; pasó la revisión porque las pruebas corrían como admin. Queda documentado en `INCIDENT.md` como "por qué pasó la revisión".
- La solución traída no identificaba el commit culpable ni revisaba el patrón en otras partes (requisitos del Tramo B y C): se completó con `git log`/`git show` y grep sobre el módulo.

## Lo que escribiste tú sin IA
- El ticket, las reglas del ejercicio y la prioridad explícita: "menor ajuste posible, prioridad al flujo de trabajo".
- La decisión de priorizar contención + hotfix sin reescribir el módulo, y de dejar `action_recompute_commissions()` para otro ticket en vez de tocarlo.
- El mensaje al cliente y la validación de las pruebas (las ejecutás vos).
