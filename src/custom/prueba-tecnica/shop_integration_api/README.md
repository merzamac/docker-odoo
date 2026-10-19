# Shop Integration API (`shop_integration_api`)

Módulo para **Odoo 18.0** que expone una API REST para que una tienda en línea
sincronice catálogo, cree pedidos de venta y reciba notificaciones de despacho.

## Tramos completados

- **Tramo A**: `GET /api/v1/products` con autenticación `user`. Filtros
  combinables (categoría, solo-con-stock, modificados-desde), respuesta JSON con
  id/código/nombre/precio/stock, y fecha inválida → `422` con error claro (nunca
  500).
- **Tramo B**: autenticación `Authorization: Bearer` con las API keys nativas
  (`res.users.apikeys`). `POST /api/v1/orders` crea el pedido validando RIF,
  producto y cantidad con el formato de error del enunciado. **Todas** las
  llamadas (exitosas y fallidas) quedan en `api.request.log`; el log no guarda
  la clave. Pruebas con `HttpCase`.
- **Tramo C**: paginación con metadatos (`total`, `page`, `has_next`), cabecera
  `Idempotency-Key` (misma clave + mismo contenido → mismo pedido; distinto
  contenido → `409`), stock calculado en lote (sin consulta por producto, con
  prueba que compara contadores de queries) y webhook saliente desacoplado con
  reintentos vía cron.

## Cómo probarlo

El comando del repositorio crea su propia base, instala el módulo y corre las
pruebas (no requiere preparación previa):

```bash
# PowerShell
$env:PYTHONUTF8="1"
python odoo test -i prueba -m shop_integration_api

# Con una base propia que ya existe (la crea si falta con -d)
python odoo test -i prueba -m shop_integration_api -d prueba_limpia
```

Prueba manual con curl (una vez instalado en una base):

```powershell
# Tramo A: requiere sesión de browser (auth='user'); probar desde http://localhost:8070
# Tramo B: crear una API key en Preferencias > Seguridad > Claves de API
curl -X POST http://localhost:8070/api/v1/orders `
  -H "Authorization: Bearer <API_KEY>" `
  -H "Content-Type: application/json" `
  -H "Idempotency-Key: DEMO-001" `
  -d "{\"rif\":\"J-12345678-0\",\"external_reference\":\"REF-1\",\"lines\":[{\"default_code\":\"ABC-123\",\"quantity\":2}]}"
```

Para el webhook: definir el parámetro `shop.webhook_delivery_url`
(Ajustes > Técnico > Parámetros del Sistema), validar una entrega y ver el
estado en **Ajustes > Integración API > Cola de Webhooks** (el cron reintenta
cada 5 minutos, máximo 5 intentos).

## Endpoints

Ver `openapi.yaml` (OpenAPI 3.0). Resumen:

| Método | Ruta | Auth | Errores |
|--------|------|------|---------|
| GET | `/api/v1/products` | sesión (`user`) | 422 `INVALID_FILTER`, `INVALID_DATE_FORMAT`, `INVALID_PAGINATION` |
| POST | `/api/v1/orders` | API key (Bearer) | 401, 409, 422, 201 |

Formato de error:

```json
{
  "error": {
    "code": "PRODUCT_NOT_FOUND",
    "field": "lines[0].default_code",
    "message": "No existe un producto con el codigo ABC-123"
  }
}
```

## Supuestos y limitaciones

- **Pedido confirmado**: el POST crea el pedido y lo confirma
  (`action_confirm()`), porque proviene de compras ya autorizadas en la web y es
  lo que inicializa el `stock.picking` que dispara el webhook. Si querés
  cotizaciones en borrador, hay que quitar esa línea y el webhook no disparará
  hasta confirmar a mano.
- **RIF**: se asume que el RIF vive en `res.partner.vat`. No se valida formato
  (eso lo hace `base_vat`, que no está en los dependencias).
- **`qty_available` vs `free_qty`**: el filtro `only_stock` y el campo de la
  respuesta usan `qty_available` (stock físico). Si necesitás stock *libre* (ya
  reservado descontado), cambiar el dominio y `quantities[p.id]['free_qty']`.
- **Claves de idempotencia globales**: la `Idempotency-Key` es única en toda la
  tabla; dos integraciones distintas no deberían reutilizar claves entre sí.
- **Webhook at-least-once**: si Odoo confirma el envío pero la respuesta se
  pierde, el registro se reenvía. La tienda debe tolerar duplicados (el campo
  `picking_name` sirve como idempotente del lado de ellos).
- El cron de reintentos no cubre respuestas 4xx de la tienda como errores
  transitorios: cualquier no-2xx cuenta como intento y a los 5 el registro queda
  `failed` (visible en la cola para diagnóstico).
- **Auditoría**: solo registra respuestas que emite la API (200/201/401/409/422/
  500). Una petición sin sesión al GET redirige al login y no llega al controller
  (por diseño de `auth='user'`).

## Pruebas incluidas (22)

- Tramo A: filtros solos y combinados, fecha/paginación inválidas → 422.
- Tramo B: 401 sin clave y con clave inválida, RIF/producto/cantidad con `field`
  exacto, creación del pedido, **log de llamadas fallidas**, y que el log no
  contiene la clave.
- Tramo C: paginación con metadatos, idempotencia (replay y 409), **contador de
  queries que no crece con 200 productos**, webhook encolado sin bloquear la
  entrega y reintentos cuando la tienda está caída.

Los tests crean su propio usuario API (no dependen de datos demo; el comando
del repositorio corre con `--without-demo=True`).
