import hashlib
import json
import logging
import time
from datetime import date, datetime

from psycopg2 import IntegrityError

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

MAX_PAGE_LIMIT = 100


def _error_payload(code, message, field=None):
    """Formato de error documentado en el enunciado (Tramo B)."""
    error = {'code': code, 'message': message}
    if field:
        error['field'] = field
    return {'error': error}


def _json_response(payload, status, *, endpoint, user, start_time, error_message=None):
    """Devuelve la respuesta JSON y registra la llamada en la auditoria.

    Se usa para TODAS las respuestas (exitosas y fallidas): el Tramo B
    exige que las llamadas fallidas tambien queden en el log.
    """
    request.env['api.request.log'].sudo().create({
        'endpoint': endpoint,
        'user_id': user.id if user else False,
        'status_code': status,
        'duration': (time.time() - start_time) * 1000.0,
        'ip_address': request.httprequest.remote_addr,
        'error_message': error_message,
    })
    return Response(
        json.dumps(payload),
        status=status,
        headers=[('Content-Type', 'application/json')],
    )


def _error_response(code, message, *, status, endpoint, user, start_time, field=None):
    return _json_response(
        _error_payload(code, message, field), status,
        endpoint=endpoint, user=user, start_time=start_time,
        error_message='%s: %s' % (code, message),
    )


def _parse_iso_date(value):
    """Acepta fecha completa (YYYY-MM-DDTHH:MM:SS) o solo fecha (YYYY-MM-DD)."""
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _authenticate_api_key():
    """Tramo B: valida `Authorization: Bearer <key>` con res.users.apikeys."""
    header = request.httprequest.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return False
    key = header.split(' ', 1)[1].strip()
    if not key:
        return False
    user_id = request.env['res.users.apikeys'].sudo()._check_credentials(
        scope='rpc', key=key)
    return request.env['res.users'].browse(user_id) if user_id else False


class ShopApiController(http.Controller):

    # ------------------------------------------------------------------
    # Tramo A/C: catalogo de productos
    # ------------------------------------------------------------------
    @http.route('/api/v1/products', type='http', auth='user', methods=['GET'], csrf=False)
    def get_products(self, **kwargs):
        start = time.time()
        endpoint = '/api/v1/products'
        user = request.env.user
        try:
            # Solo productos activos y vendibles.
            domain = [('sale_ok', '=', True), ('active', '=', True)]

            category_id = kwargs.get('category_id')
            if category_id:
                try:
                    domain.append(('categ_id', '=', int(category_id)))
                except ValueError:
                    return _error_response(
                        'INVALID_FILTER', 'El ID de categoria debe ser entero',
                        status=422, field='category_id',
                        endpoint=endpoint, user=user, start_time=start)

            modified_since = kwargs.get('modified_since')
            if modified_since:
                if _parse_iso_date(modified_since) is None:
                    return _error_response(
                        'INVALID_DATE_FORMAT',
                        'Formato de fecha invalido. Utilice ISO-8601 (YYYY-MM-DDTHH:MM:SS)',
                        status=422, field='modified_since',
                        endpoint=endpoint, user=user, start_time=start)
                domain.append(('write_date', '>=', modified_since))

            only_stock = str(kwargs.get('only_stock', '')).lower() in ('true', '1', 'yes')
            if only_stock:
                domain.append(('qty_available', '>', 0))

            # Tramo C: paginacion con metadatos.
            try:
                page = max(1, int(kwargs.get('page', 1)))
                limit = min(MAX_PAGE_LIMIT, max(1, int(kwargs.get('limit', 20))))
            except ValueError:
                return _error_response(
                    'INVALID_PAGINATION', 'Pagina y limite deben ser numeros enteros',
                    status=422, endpoint=endpoint, user=user, start_time=start)

            Product = request.env['product.product']
            total = Product.search_count(domain)
            offset = (page - 1) * limit
            products = Product.search(domain, offset=offset, limit=limit, order='id asc')

            # Calculo masivo de stock en un solo lote: evita una consulta
            # por producto (Tramo C: N+1).
            quantities = products._compute_quantities_dict(False, False, False)

            data = [{
                'id': p.id,
                'default_code': p.default_code or '',
                'name': p.display_name,
                'list_price': p.list_price,
                'qty_available': quantities[p.id]['qty_available'],
            } for p in products]

            return _json_response({
                'total': total,
                'page': page,
                'limit': limit,
                'has_next': (offset + limit) < total,
                'data': data,
            }, 200, endpoint=endpoint, user=user, start_time=start)
        except Exception:
            _logger.exception('Fallo inesperado en %s', endpoint)
            request.env.cr.rollback()
            return _error_response(
                'INTERNAL_ERROR', 'Error interno del servidor',
                status=500, endpoint=endpoint, user=user, start_time=start)

    # ------------------------------------------------------------------
    # Tramo B/C: creacion de pedidos
    # ------------------------------------------------------------------
    @http.route('/api/v1/orders', type='http', auth='none', methods=['POST'], csrf=False)
    def create_order(self, **kwargs):
        start = time.time()
        endpoint = '/api/v1/orders'
        user = _authenticate_api_key()
        if not user:
            return _error_response(
                'UNAUTHORIZED', 'API Key invalida o no suministrada.',
                status=401, endpoint=endpoint, user=False, start_time=start)

        # Operamos con los permisos del usuario de la API key (sin sudo):
        # si no puede crear pedidos, el error es 500 y queda en el log.
        env = request.env(user=user)
        try:
            return self._create_order(env, endpoint, user, start)
        except Exception:
            _logger.exception('Fallo inesperado en %s', endpoint)
            request.env.cr.rollback()
            return _error_response(
                'INTERNAL_ERROR', 'Error interno del servidor',
                status=500, endpoint=endpoint, user=user, start_time=start)

    def _create_order(self, env, endpoint, user, start):
        raw_body = request.httprequest.data.decode('utf-8', errors='replace')
        try:
            body = json.loads(raw_body)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return _error_response(
                'INVALID_JSON', 'El cuerpo de la peticion debe ser JSON valido',
                status=422, endpoint=endpoint, user=user, start_time=start)

        # Tramo C: idempotencia. La clave se guarda en la misma transaccion
        # que el pedido; si otra peticion gana la carrera, aqui se reproduce
        # su respuesta en vez de crear un segundo pedido.
        idempotency_key = request.httprequest.headers.get('Idempotency-Key')
        payload_hash = hashlib.sha256(raw_body.encode('utf-8')).hexdigest()
        if idempotency_key:
            replay = self._idempotent_replay(env, idempotency_key, payload_hash, endpoint, user, start)
            if replay is not None:
                return replay

        # Validaciones de negocio (Tramo B).
        rif = body.get('rif')
        if not rif or not isinstance(rif, str):
            return _error_response(
                'MISSING_FIELD', 'El RIF del cliente es obligatorio',
                status=422, field='rif',
                endpoint=endpoint, user=user, start_time=start)

        partner = env['res.partner'].search([('vat', '=', rif)], limit=1)
        if not partner:
            return _error_response(
                'PARTNER_NOT_FOUND', 'No se encontro ningun cliente con el RIF %s' % rif,
                status=422, field='rif',
                endpoint=endpoint, user=user, start_time=start)

        lines = body.get('lines')
        if not isinstance(lines, list) or not lines:
            return _error_response(
                'INVALID_LINES', 'Debe proporcionar una lista de lineas de pedido',
                status=422, field='lines',
                endpoint=endpoint, user=user, start_time=start)

        # Una sola consulta para todos los codigos del pedido.
        codes = {
            line.get('default_code') for line in lines
            if isinstance(line, dict) and isinstance(line.get('default_code'), str)
        }
        products = {
            p.default_code: p
            for p in env['product.product'].search([('default_code', 'in', list(codes)), ('sale_ok', '=', True)])
        }

        order_lines = []
        for index, line in enumerate(lines):
            if not isinstance(line, dict):
                return _error_response(
                    'INVALID_LINES', 'Cada linea debe ser un objeto JSON',
                    status=422, field='lines[%d]' % index,
                    endpoint=endpoint, user=user, start_time=start)

            code = line.get('default_code')
            product = products.get(code) if isinstance(code, str) else None
            if not product:
                return _error_response(
                    'PRODUCT_NOT_FOUND', 'No existe un producto con el codigo %s' % (code,),
                    status=422, field='lines[%d].default_code' % index,
                    endpoint=endpoint, user=user, start_time=start)

            qty = line.get('quantity', 0)
            if isinstance(qty, bool) or not isinstance(qty, (int, float)) or qty <= 0:
                return _error_response(
                    'INVALID_QUANTITY', 'La cantidad debe ser un numero estrictamente positivo',
                    status=422, field='lines[%d].quantity' % index,
                    endpoint=endpoint, user=user, start_time=start)

            order_lines.append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'price_unit': product.list_price,
            }))

        # Supuesto (documentado en README): el pedido llega confirmado para
        # disparar el flujo de entrega y, con el, el webhook del Tramo C.
        response_payload = None
        try:
            with request.env.cr.savepoint():
                order = env['sale.order'].create({
                    'partner_id': partner.id,
                    'client_order_ref': body.get('external_reference'),
                    'order_line': order_lines,
                })
                order.action_confirm()
                response_payload = {
                    'id': order.id,
                    'name': order.name,
                    'state': order.state,
                    'amount_total': order.amount_total,
                }
                if idempotency_key:
                    env['api.idempotency'].sudo().create({
                        'key': idempotency_key,
                        'request_hash': payload_hash,
                        'order_id': order.id,
                        'response_code': 201,
                        'response_body': json.dumps(response_payload),
                    })
                request.env.cr.flush()
        except (IntegrityError, ValidationError):
            # La unica violacion esperada aqui es la clave de idempotencia
            # tomada por otra peticion concurrente (el savepoint ya reverso
            # la creacion de este intento).
            existing = False
            if idempotency_key:
                existing = env['api.idempotency'].sudo().search(
                    [('key', '=', idempotency_key)], limit=1)
            if not existing:
                raise
            if existing.request_hash != payload_hash:
                return _error_response(
                    'IDEMPOTENCY_CONFLICT',
                    'La clave fue usada con un cuerpo de datos distinto.',
                    status=409, endpoint=endpoint, user=user, start_time=start)
            return _json_response(
                json.loads(existing.response_body), existing.response_code,
                endpoint=endpoint, user=user, start_time=start)

        return _json_response(
            response_payload, 201,
            endpoint=endpoint, user=user, start_time=start)

    def _idempotent_replay(self, env, key, payload_hash, endpoint, user, start):
        """Devuelve la respuesta cacheada si la clave ya fue usada, o None."""
        existing = env['api.idempotency'].sudo().search([('key', '=', key)], limit=1)
        if not existing:
            return None
        if existing.request_hash != payload_hash:
            return _error_response(
                'IDEMPOTENCY_CONFLICT',
                'La clave fue usada con un cuerpo de datos distinto.',
                status=409, endpoint=endpoint, user=user, start_time=start)
        return _json_response(
            json.loads(existing.response_body), existing.response_code,
            endpoint=endpoint, user=user, start_time=start)
