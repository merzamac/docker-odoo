from odoo import fields, models


class ApiIdempotency(models.Model):
    _name = 'api.idempotency'
    _description = 'Registro de Idempotencia de API'
    _order = 'create_date desc'

    key = fields.Char(string='Idempotency Key', required=True, index=True)
    request_hash = fields.Char(string='Payload Hash', required=True)
    order_id = fields.Many2one('sale.order', string='Pedido Creado', ondelete='cascade')
    response_code = fields.Integer(string='Codigo de Respuesta')
    response_body = fields.Text(string='Cuerpo de Respuesta')

    _sql_constraints = [
        ('key_unique', 'unique(key)', 'La clave de idempotencia debe ser unica.')
    ]
