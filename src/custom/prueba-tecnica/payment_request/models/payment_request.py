import psycopg2
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class PaymentRequest(models.Model):
    _name = "payment.request"
    _description = "Solicitud de Pago"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(string="Secuencia", required=True, copy=False, readonly=True, default="/")
    partner_id = fields.Many2one("res.partner", string="Proveedor", required=True, tracking=True)
    applicant_id = fields.Many2one(
        "res.users",
        string="Solicitante",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    amount = fields.Monetary(string="Monto", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today, tracking=True)
    concept = fields.Text(string="Concepto", required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("sent", "Enviada"),
            ("approved", "Aprobada"),
            ("paid", "Pagada"),
            ("rejected", "Rechazada"),
        ],
        string="Estado",
        default="draft",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    assigned_approver_id = fields.Many2one("res.users", string="Aprobador Asignado", tracking=True)
    approver_id = fields.Many2one("res.users", string="Aprobado Por", readonly=True, copy=False)
    approval_date = fields.Datetime(string="Fecha de Aprobación", readonly=True, copy=False)
    payment_id = fields.Many2one("account.payment", string="Pago Contable", readonly=True, copy=False)

    _sql_constraints = [
        ("name_uniq", "unique(name)", "La secuencia de la solicitud debe ser única."),
    ]

    @api.constrains("amount")
    def _check_amount_positive(self):
        for req in self:
            if req.amount <= 0:
                raise ValidationError(_("El monto de la solicitud debe ser estrictamente mayor a cero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("payment.request") or "/"
        return super().create(vals_list)

    def write(self, vals):
        # Bloquear edición si ya fue enviada (Tramo A)
        for req in self:
            if req.state != "draft" and any(f in vals for f in ["amount", "partner_id", "currency_id", "concept", "date"]):
                raise UserError(_("Una solicitud enviada, aprobada o pagada no puede ser modificada."))
        return super().write(vals)

    def action_send(self):
        for req in self:
            if req.state != "draft":
                raise UserError(_("Solo se pueden enviar solicitudes en estado Borrador."))

            # Tramo B: Determinar nivel de aprobación según el monto en la compañía
            levels = self.env["payment.approval.level"].search([
                ("company_id", "=", req.company_id.id),
                ("min_amount", "<=", req.amount),
            ], order="min_amount desc")

            approver = levels[:1].approver_id if levels else False
            if not approver:
                # Si no hay nivel configurado, escala a un usuario aprobador por defecto
                approver = self.env["res.users"].search([
                    ("groups_id", "in", self.env.ref("payment_request.group_payment_request_approver").id),
                    ("company_ids", "in", req.company_id.id),
                ], limit=1)

            req.assigned_approver_id = approver
            req.state = "sent"

            # Crear actividad para el aprobador asignado
            if approver:
                req.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=approver.id,
                    summary=_("Aprobación pendiente para solicitud %s de %s %s") % (req.name, req.amount, req.currency_id.symbol),
                )

    def action_approve(self):
        """Tramo A, B y C: Aprobación estricta con bloqueo pesimista en PostgreSQL."""
        for req in self:
            # 1. Seguridad de Rol (Tramo A)
            if not self.env.user.has_group("payment_request.group_payment_request_approver"):
                raise AccessError(_("No tiene permisos de aprobador para realizar esta acción."))

            # 2. Asignación de Aprobador (Tramo B)
            if req.assigned_approver_id and self.env.user != req.assigned_approver_id and not self.env.is_admin():
                raise UserError(_("Solo el aprobador asignado (%s) puede aprobar esta solicitud.") % req.assigned_approver_id.name)

            # 3. Tramo C: Bloqueo Pesimista en Base de Datos (Row-Level Locking)
            try:
                self.env.cr.execute(
                    "SELECT id, state FROM payment_request WHERE id = %s FOR UPDATE NOWAIT",
                    [req.id],
                    log_exceptions=False,
                )
                row = self.env.cr.fetchone()
            except psycopg2.OperationalError:
                raise UserError(_("La solicitud está siendo procesada concurrentemente por otro usuario. Intente nuevamente."))

            if not row or row[1] != "sent":
                raise UserError(_("La solicitud %s ya fue procesada o no se encuentra en estado Enviada.") % req.name)

            # 4. Finalizar actividades pendientes y registrar trazabilidad para el PDF
            req.activity_feedback(["mail.mail_activity_data_todo"])
            req.write({
                "state": "approved",
                "approver_id": self.env.user.id,
                "approval_date": fields.Datetime.now(),
            })
            req.message_post(body=_("Solicitud aprobada por %s.") % self.env.user.name)

    def action_open_reject_wizard(self):
        return {
            "name": _("Rechazar Solicitud de Pago"),
            "type": "ir.actions.act_window",
            "res_model": "payment.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def action_open_pay_wizard(self):
        return {
            "name": _("Registrar Pago"),
            "type": "ir.actions.act_window",
            "res_model": "payment.request.pay.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }
