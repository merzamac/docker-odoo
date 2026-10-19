import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged

API_KEY_HEADER = 'Authorization'


@tagged('post_install', '-at_install')
class TestShopApi(HttpCase):
    """Pruebas de los tres tramos del Ejercicio 1.

    Los usuarios y claves se crean en el propio setUpClass: los tests NO
    dependen de los datos demo (el comando `./odoo test` del repositorio
    crea la base con --without-demo=True).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.categ = cls.env['product.category'].create({'name': 'Categoria API'})
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente Pruebas',
            'vat': 'J-12345678-0',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Widget Test',
            'default_code': 'ABC-123',
            'list_price': 50.0,
            'type': 'consu',
            # Odoo 18: los quants solo se crean para productos is_storable.
            'is_storable': True,
            'categ_id': cls.categ.id,
        })
        cls.extra_product = cls.env['product.product'].create({
            'name': 'Gadget Extra',
            'default_code': 'XYZ-999',
            'list_price': 10.0,
            'type': 'consu',
            'sale_ok': False,
        })
        # Usuario API con permisos de venta (no usa sudo en los controllers).
        cls.api_user = cls.env['res.users'].create({
            'name': 'Shop API User',
            'login': 'shop_api_test',
            'email': 'shop_api_test@example.org',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('sales_team.group_sale_salesman_all_leads').id,
            ])],
        })
        cls.api_key = cls.env['res.users.apikeys'].with_user(cls.api_user).sudo()._generate(
            'rpc', 'Shop Integration Key', fields.Date.today() + timedelta(days=365))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _auth_headers(self, extra=None):
        headers = {
            API_KEY_HEADER: 'Bearer %s' % self.api_key,
            'Content-Type': 'application/json',
        }
        headers.update(extra or {})
        return headers

    def _post_order(self, payload, extra_headers=None):
        return self.url_open(
            '/api/v1/orders',
            data=json.dumps(payload),
            headers=self._auth_headers(extra_headers),
        )

    def _valid_payload(self, qty=1):
        return {
            'rif': self.partner.vat,
            'external_reference': 'REF-TEST-1',
            'lines': [{'default_code': self.product.default_code, 'quantity': qty}],
        }

    # ------------------------------------------------------------------
    # Tramo A: filtros del catalogo
    # ------------------------------------------------------------------
    def test_01_products_invalid_date_returns_422(self):
        """Una fecha mal escrita devuelve 422, no 500."""
        self.authenticate('admin', 'admin')
        res = self.url_open('/api/v1/products?modified_since=fecha_invalida')
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()['error']['code'], 'INVALID_DATE_FORMAT')
        self.assertEqual(res.json()['error']['field'], 'modified_since')

    def test_02_products_invalid_pagination_returns_422(self):
        self.authenticate('admin', 'admin')
        res = self.url_open('/api/v1/products?page=abc')
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()['error']['code'], 'INVALID_PAGINATION')

    def test_03_products_category_filter(self):
        self.authenticate('admin', 'admin')
        res = self.url_open('/api/v1/products?category_id=%s' % self.categ.id)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['data'][0]['default_code'], 'ABC-123')

        res = self.url_open('/api/v1/products?category_id=999999')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['total'], 0)

    def test_04_products_only_stock_and_sellable(self):
        """Solo con stock > 0; y nunca devuelve productos no vendibles."""
        self.authenticate('admin', 'admin')
        # El producto extra no es vendible: jamas aparece en el catalogo.
        res = self.url_open('/api/v1/products?limit=100')
        codes = [p['default_code'] for p in res.json()['data']]
        self.assertIn('ABC-123', codes)
        self.assertNotIn('XYZ-999', codes)

        # Con stock en 0, el filtro only_stock lo excluye.
        res = self.url_open('/api/v1/products?only_stock=true&limit=100')
        self.assertNotIn(
            'ABC-123', [p['default_code'] for p in res.json()['data']])

        self.env['stock.quant']._update_available_quantity(
            self.product, self.env.ref('stock.stock_location_stock'), 5)
        res = self.url_open('/api/v1/products?only_stock=true&limit=100')
        self.assertIn(
            'ABC-123', [p['default_code'] for p in res.json()['data']])

    def test_05_products_modified_since(self):
        self.authenticate('admin', 'admin')
        before = fields.Datetime.now() - timedelta(days=1)
        after = fields.Datetime.now() + timedelta(days=1)

        res = self.url_open('/api/v1/products?modified_since=%s' % before.isoformat())
        self.assertEqual(res.json()['total'], 1)

        res = self.url_open('/api/v1/products?modified_since=%s' % after.isoformat())
        self.assertEqual(res.json()['total'], 0)

        # Fecha solo (YYYY-MM-DD) tambien es valida.
        res = self.url_open('/api/v1/products?modified_since=%s' % fields.Date.today().isoformat())
        self.assertEqual(res.status_code, 200)

    def test_06_products_filters_combined(self):
        """Los filtros funcionan combinados."""
        self.authenticate('admin', 'admin')
        res = self.url_open(
            '/api/v1/products?category_id=%s&only_stock=true&modified_since=%s'
            % (self.categ.id, (fields.Datetime.now() - timedelta(days=1)).isoformat()))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['total'], 0)  # sin stock todavia

        res = self.url_open(
            '/api/v1/products?category_id=999999&only_stock=true')
        self.assertEqual(res.json()['total'], 0)

    # ------------------------------------------------------------------
    # Tramo A/C: paginacion y queries acotadas
    # ------------------------------------------------------------------
    def test_07_products_pagination_metadata(self):
        self.authenticate('admin', 'admin')
        res = self.url_open('/api/v1/products?page=1&limit=1')
        body = res.json()
        self.assertEqual(body['page'], 1)
        self.assertEqual(body['limit'], 1)
        self.assertEqual(len(body['data']), 1)
        self.assertEqual(body['total'], 1)
        self.assertFalse(body['has_next'])

    def test_08_products_query_count_does_not_grow(self):
        """Tramo C: el numero de consultas del GET no crece con mas productos."""
        from odoo.sql_db import Cursor

        self.authenticate('admin', 'admin')
        counter = []
        original_execute = Cursor.execute

        def counting_execute(cursor_self, query, params=None, log_exceptions=True):
            counter.append(query)
            return original_execute(cursor_self, query, params, log_exceptions)

        def count_get_queries():
            del counter[:]
            with patch.object(Cursor, 'execute', counting_execute):
                res = self.url_open('/api/v1/products?limit=100')
            self.assertEqual(res.status_code, 200)
            return len(counter)

        # Medicion base con 1 producto (la primera corrida calienta sesion y caches).
        baseline = count_get_queries()
        self.env['product.product'].create([{
            'name': 'Producto masivo %s' % i,
            'default_code': 'BULK-%04d' % i,
            'list_price': 5.0,
            'type': 'consu',
        } for i in range(200)])
        grown = count_get_queries()

        # El patch de Cursor.execute es global y tambien cuenta consultas de
        # otros hilos del proceso (GC de filestore, cron): ruido medido ~+6.
        # El endpoint batcheado paso de 36 a 39 consultas con 100 productos
        # (access log de Odoo); un N+1 real sumaria >= +99.
        self.assertLessEqual(grown, baseline + 20)

    # ------------------------------------------------------------------
    # Tramo B: autenticacion y errores de validacion
    # ------------------------------------------------------------------
    def test_09_orders_without_key_returns_401(self):
        res = self.url_open(
            '/api/v1/orders',
            data=json.dumps(self._valid_payload()),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()['error']['code'], 'UNAUTHORIZED')

    def test_10_orders_with_invalid_key_returns_401(self):
        res = self.url_open(
            '/api/v1/orders',
            data=json.dumps(self._valid_payload()),
            headers=self._auth_headers({'Authorization': 'Bearer clave-invalida'}),
        )
        self.assertEqual(res.status_code, 401)

    def test_11_orders_invalid_json_returns_422(self):
        res = self.url_open(
            '/api/v1/orders',
            data='esto no es json',
            headers=self._auth_headers(),
        )
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()['error']['code'], 'INVALID_JSON')

    def test_12_orders_missing_rif_returns_422(self):
        res = self._post_order({'lines': [{'default_code': 'ABC-123', 'quantity': 1}]})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()['error']['code'], 'MISSING_FIELD')
        self.assertEqual(res.json()['error']['field'], 'rif')

    def test_13_orders_unknown_rif_returns_422(self):
        res = self._post_order({
            'rif': 'J-00000000-0',
            'lines': [{'default_code': 'ABC-123', 'quantity': 1}],
        })
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()['error']['code'], 'PARTNER_NOT_FOUND')
        self.assertEqual(res.json()['error']['field'], 'rif')

    def test_14_orders_unknown_product_returns_field_path(self):
        res = self._post_order({
            'rif': self.partner.vat,
            'lines': [{'default_code': 'NO-EXISTE', 'quantity': 2}],
        })
        self.assertEqual(res.status_code, 422)
        error = res.json()['error']
        self.assertEqual(error['code'], 'PRODUCT_NOT_FOUND')
        self.assertEqual(error['field'], 'lines[0].default_code')

    def test_15_orders_invalid_quantity_returns_field_path(self):
        for qty in (0, -3, 'dos'):
            res = self._post_order(self._valid_payload(qty=qty))
            self.assertEqual(res.status_code, 422, qty)
            error = res.json()['error']
            self.assertEqual(error['code'], 'INVALID_QUANTITY', qty)
            self.assertEqual(error['field'], 'lines[0].quantity', qty)

    # ------------------------------------------------------------------
    # Tramo B: creacion y auditoria
    # ------------------------------------------------------------------
    def test_16_order_created_and_confirmed(self):
        res = self._post_order(self._valid_payload())
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertEqual(body['state'], 'sale')

        order = self.env['sale.order'].browse(body['id'])
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(order.client_order_ref, 'REF-TEST-1')
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_uom_qty, 1)

    def test_17_failed_calls_are_logged(self):
        """Tramo B: las llamadas fallidas TAMBIEN quedan en el log."""
        Log = self.env['api.request.log']
        before = Log.search_count([])
        res = self._post_order({'rif': 'J-00000000-0', 'lines': []})
        self.assertEqual(res.status_code, 422)
        log = Log.search([], order='id desc', limit=1)
        self.assertEqual(Log.search_count([]), before + 1)
        self.assertEqual(log.status_code, 422)
        self.assertIn('PARTNER_NOT_FOUND', log.error_message or '')

    def test_18_log_does_not_store_api_key(self):
        res = self._post_order(self._valid_payload())
        self.assertEqual(res.status_code, 201)
        log = self.env['api.request.log'].search([], order='id desc', limit=1)
        self.assertNotIn(self.api_key, json.dumps(log.read(), default=str))
        self.assertNotIn(self.api_key, log.error_message or '')

    # ------------------------------------------------------------------
    # Tramo C: idempotencia
    # ------------------------------------------------------------------
    def test_19_idempotency_same_payload_returns_same_order(self):
        headers = {'Idempotency-Key': 'IDEM-SAME-001'}
        res1 = self._post_order(self._valid_payload(), headers)
        res2 = self._post_order(self._valid_payload(), headers)
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(res1.json()['id'], res2.json()['id'])
        self.assertEqual(self.env['sale.order'].search_count(
            [('partner_id', '=', self.partner.id)]), 1)

    def test_20_idempotency_different_payload_returns_409(self):
        headers = {'Idempotency-Key': 'IDEM-CONFLICT-001'}
        res1 = self._post_order(self._valid_payload(qty=1), headers)
        self.assertEqual(res1.status_code, 201)
        res2 = self._post_order(self._valid_payload(qty=5), headers)
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.json()['error']['code'], 'IDEMPOTENCY_CONFLICT')

    # ------------------------------------------------------------------
    # Tramo C: webhook desacoplado
    # ------------------------------------------------------------------
    def test_21_delivery_enqueues_webhook_without_blocking(self):
        """Validar la entrega encola el aviso; no hace HTTP en la transaccion."""
        self.env['ir.config_parameter'].sudo().set_param(
            'shop.webhook_delivery_url', 'http://127.0.0.1:1/webhook-shop')
        res = self._post_order(self._valid_payload())
        self.assertEqual(res.status_code, 201)
        order = self.env['sale.order'].browse(res.json()['id'])
        picking = order.picking_ids
        self.assertTrue(picking, 'La confirmacion deberia crear una entrega')

        Queue = self.env['api.webhook.queue']
        Queue.search([]).unlink()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()

        self.assertEqual(picking.state, 'done')
        queued = Queue.search([])
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued.state, 'pending')
        payload = json.loads(queued.payload)
        self.assertEqual(payload['event'], 'delivery_validated')
        self.assertEqual(payload['order_reference'], 'REF-TEST-1')

    def test_22_webhook_retries_when_store_is_down(self):
        """Tienda caida: el reintento falla sin excepcion y queda registrado."""
        self.env['ir.config_parameter'].sudo().set_param(
            'shop.webhook_delivery_url', 'http://127.0.0.1:1/webhook-shop')
        Queue = self.env['api.webhook.queue']
        record = Queue.create({
            'url': 'http://127.0.0.1:1/webhook-shop',
            'payload': json.dumps({'event': 'delivery_validated'}),
        })
        Queue.process_webhook_queue()
        self.assertEqual(record.attempts, 1)
        self.assertEqual(record.state, 'pending')
        self.assertTrue(record.last_error)
