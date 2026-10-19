from odoo import fields, models


class ApiRequestLog(models.Model):
    _name = 'api.request.log'
    _description = 'Registro de Auditoria API'
    _order = 'create_date desc'

    endpoint = fields.Char(string='Endpoint', required=True, index=True)
    user_id = fields.Many2one('res.users', string='Usuario', ondelete='set null')
    status_code = fields.Integer(string='Codigo HTTP', required=True)
    duration = fields.Float(string='Duracion (ms)', digits=(12, 2))
    ip_address = fields.Char(string='Direccion IP')
    error_message = fields.Text(string='Detalle del Error')
