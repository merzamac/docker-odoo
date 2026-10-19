# AI_LOG — fleet_inspection

## Herramientas
- Asistente de IA en OpenCode (modelo MiMo) — migración a Odoo 18, diagnósticos y commits.
- ChatGPT — generó la solución base del Tramo A (migración + scripts), que se pegó y verificó aquí.

## Prompts clave (3 a 5)
1. "Te presento la solución integral y definitiva del Ejercicio 2… solo pasar el módulo a prueba-tecnica"
   - Recibí el módulo Tramo A completo; se escribió al repo y se verificó contra la fuente de Odoo 18.
2. "¿Cómo hago para yo mismo ejecutar las pruebas?"
   - Documentó los comandos (`python odoo test -i prueba -m fleet_inspection`) y dejó claras las pruebas como tarea propia.
3. "La vista de formulario no carga bien… solo veo el nombre del modelo del documento" (+capturas)
   - Diagnosticó por logs, arch en BD y fuente de `mail` hasta hallar la causa raíz.
4. "Debemos hacer commit de este módulo"
   - Plan de commits con prefijos [MIG]/[TEST]/[FIX]/[DOC] y ejecución en rama.
5. "¿Cuáles son los tipos de vehículo que tengo?"
   - Consultó la BD en solo lectura y explicó la diferencia entre el selection del módulo y el `vehicle_type` del core Fleet.

## Lo que la IA hizo mal
- La solución "definitiva" traída incluía `<field name="doall" eval="False"/>` en el cron: `doall` fue eliminado de `ir.cron` en Odoo 18 (igual que `numbercall`); instalada tal cual, el módulo no instala ("Invalid field"). Cómo se detectó: verificación con grep contra la fuente real de Odoo 18 antes de escribir el archivo.
- El plan de migración completo pasó por alto el cambio `<div class="oe_chatter">` → `<chatter/>` de Odoo 18. Resultado: el hilo se renderizaba como 3 listas crudas en el formulario. Cómo se detectó: prueba manual en PC/tablet (capturas) + lectura del compilador de vistas de `mail` en el contenedor. Corregido con commit [FIX] `76ff9b7`.
- El test original usaba `name_get()` (eliminado en 18) y el import `odoo.tests.common.Form` (deprecado en 18): ambos detectados leyendo la fuente de Odoo 18, no a ciegas.
- La versión pegada de las vistas omitía la vista de búsqueda (filtros y agrupaciones) y el `help` de la acción; se comparó con el original, se preguntó y se restauró.

## Lo que escribiste tú sin IA
- La decisión de arquitectura: dónde vive el módulo migrado (`src/custom/prueba-tecnica`) y mantener el original Odoo 16 intacto.
- Las pruebas manuales del formulario (PC, tablet, refresco, reinicio) que revelaron el bug del chatter que ningún grep veía.
- Los mensajes y el orden de los commits, y la exigencia de commitear solo el módulo.
