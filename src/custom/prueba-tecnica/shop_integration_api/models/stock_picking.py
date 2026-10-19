import json

from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super()._action_done()
        # El webhook se ENCOLA aqui (una insercion) y se envia despues via cron:
        # nunca se hace HTTP saliente dentro de la transaccion de validacion.
        # sudo() justificado: cualquier usuario que valide una entrega puede
        # generar el evento, pero la cola la administra solo el sistema.
        webhook_url = self.env['ir.config_parameter'].sudo().get_param(
            'shop.webhook_delivery_url')
        if not webhook_url:
            return res
        for picking in self:
            if not picking.sale_id or picking.picking_type_id.code != 'outgoing':
                continue
            payload = {
                'event': 'delivery_validated',
                'order_reference': picking.sale_id.client_order_ref or picking.sale_id.name,
                'picking_name': picking.name,
                'date_done': fields.Datetime.to_string(picking.date_done),
            }
            self.env['api.webhook.queue'].sudo().create({
                'url': webhook_url,
                'payload': json.dumps(payload),
            })
        return res
