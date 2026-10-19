from odoo import fields, models


class PaymentApprovalLevel(models.Model):
    _name = "payment.approval.level"
    _description = "Nivel de Aprobación de Pago"
    _order = "min_amount desc"

    name = fields.Char(string="Descripción", required=True)
    min_amount = fields.Monetary(string="Monto Mínimo", required=True)
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    approver_id = fields.Many2one("res.users", string="Aprobador Asignado", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
