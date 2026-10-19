from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PaymentRequestPayWizard(models.TransientModel):
    _name = "payment.request.pay.wizard"
    _description = "Wizard para Registrar Pago Contable"

    request_id = fields.Many2one("payment.request", string="Solicitud", required=True)
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario de Pago",
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        required=True,
    )
    payment_date = fields.Date(string="Fecha de Pago", default=fields.Date.context_today, required=True)
    company_id = fields.Many2one(related="request_id.company_id")
    currency_id = fields.Many2one(related="request_id.currency_id")
    amount = fields.Monetary(related="request_id.amount")

    # Moneda efectiva del pago: la del diario o, si el diario no tiene moneda propia, la de la compañía
    journal_currency_id = fields.Many2one(
        "res.currency",
        string="Moneda del Diario",
        compute="_compute_amount_in_journal_currency",
    )
    amount_in_journal_currency = fields.Monetary(
        string="Monto en Moneda del Diario",
        compute="_compute_amount_in_journal_currency",
        currency_field="journal_currency_id",
    )

    @api.depends("journal_id", "payment_date", "request_id")
    def _compute_amount_in_journal_currency(self):
        for wiz in self:
            if wiz.journal_id and wiz.request_id:
                dest_currency = wiz.journal_id.currency_id or wiz.company_id.currency_id
                # Conversión oficial de divisa en Odoo según la tasa de la fecha de pago
                wiz.amount_in_journal_currency = wiz.currency_id._convert(
                    wiz.amount, dest_currency, wiz.company_id, wiz.payment_date
                )
                wiz.journal_currency_id = dest_currency
            else:
                wiz.amount_in_journal_currency = 0.0
                wiz.journal_currency_id = False

    def action_confirm_payment(self):
        self.ensure_one()
        req = self.request_id

        # 1. Validación contra doble pago
        if req.state == "paid" or req.payment_id:
            raise UserError(_("Esta solicitud ya ha sido pagada previamente."))

        if req.state != "approved":
            raise UserError(_("Solo se pueden pagar solicitudes en estado Aprobada."))

        dest_currency = self.journal_id.currency_id or self.company_id.currency_id
        payment_amount = self.currency_id._convert(
            req.amount, dest_currency, self.company_id, self.payment_date
        )

        # 2. Integridad transaccional: Creación y confirmación del account.payment
        # Si esto falla, el motor lanzará una excepción y Odoo hará ROLLBACK automático.
        payment_vals = {
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": req.partner_id.id,
            "amount": payment_amount,
            "currency_id": dest_currency.id,
            "journal_id": self.journal_id.id,
            "date": self.payment_date,
            # En Odoo 18 account.payment ya no tiene 'ref' (vive en account.move);
            # 'memo' es su sucesor y alimenta la glosa del asiento vía _inverse_memo
            "memo": _("Pago Solicitud %s - %s") % (req.name, req.concept),
        }
        payment = self.env["account.payment"].create(payment_vals)
        payment.action_post()

        # 3. Vincular y cambiar estado
        req.write({
            "state": "paid",
            "payment_id": payment.id,
        })
        req.message_post(
            # Markup: en Odoo 18 los cuerpos str se escapan y las etiquetas se verían como texto
            body=Markup(_("Pago contable registrado exitosamente: <a href='#' data-oe-model='account.payment' data-oe-id='%s'>%s</a> por un monto de %s %s.")) % (
                payment.id, payment.name, payment.amount, dest_currency.symbol
            )
        )
        return {"type": "ir.actions.act_window_close"}
