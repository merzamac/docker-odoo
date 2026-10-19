import json
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


class ApiWebhookQueue(models.Model):
    _name = 'api.webhook.queue'
    _description = 'Cola de Envios de Webhook'
    _order = 'create_date desc'

    url = fields.Char(string='URL Destino', required=True)
    payload = fields.Text(string='Cuerpo JSON', required=True)
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('sent', 'Enviado'),
        ('failed', 'Fallido'),
    ], string='Estado', default='pending', index=True)
    attempts = fields.Integer(string='Intentos', default=0)
    last_error = fields.Text(string='Ultimo Error')

    @api.model
    def process_webhook_queue(self, limit=50):
        """Procesa la cola de webhooks pendientes con reintentos.

        El envio es siempre asincrono (cron): nunca corre dentro de la
        transaccion que valida la entrega, por lo que una tienda caida no
        bloquea ni revierte el stock.
        """
        records = self.search([
            ('state', '=', 'pending'),
            ('attempts', '<', MAX_ATTEMPTS),
        ], limit=limit)
        for record in records:
            record.attempts += 1
            try:
                res = requests.post(
                    record.url,
                    json=json.loads(record.payload),
                    headers={'Content-Type': 'application/json'},
                    timeout=5,
                )
                if 200 <= res.status_code < 300:
                    record.state = 'sent'
                    record.last_error = False
                    continue
                record.last_error = 'HTTP %s: %s' % (res.status_code, res.text[:500])
            except requests.RequestException as exc:
                record.last_error = str(exc)[:500]
            if record.attempts >= MAX_ATTEMPTS:
                record.state = 'failed'
            _logger.warning(
                'Webhook %s (intento %s/%s): %s',
                record.url, record.attempts, MAX_ATTEMPTS, record.last_error,
            )
