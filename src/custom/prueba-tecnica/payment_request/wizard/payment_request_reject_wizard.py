from odoo import _, fields, models
from odoo.exceptions import UserError


class PaymentRequestRejectWizard(models.TransientModel):
    _name = "payment.request.reject.wizard"
    _description = "Wizard para Rechazo de Solicitud de Pago"

    request_id = fields.Many2one("payment.request", string="Solicitud", required=True)
    reject_reason = fields.Text(string="Motivo de Rechazo", required=True)

    def action_reject(self):
        self.ensure_one()
        req = self.request_id
        if req.state not in ["draft", "sent"]:
            raise UserError(_("No se puede rechazar una solicitud que ya fue aprobada o pagada."))

        req.activity_feedback(["mail.mail_activity_data_todo"])
        req.write({"state": "rejected"})
        req.message_post(
            body=_("<b>Solicitud Rechazada</b> por %s.<br/><b>Motivo:</b> %s") % (self.env.user.name, self.reject_reason)
        )
        return {"type": "ir.actions.act_window_close"}
