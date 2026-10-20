from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestPaymentRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.ref("base.main_company")
        cls.company_b = cls.env["res.company"].create({"name": "Compañía B"})

        cls.user_solicitante = new_test_user(
            cls.env, login="user_solicitante", name="Solicitante Uno",
            groups="payment_request.group_payment_request_user",
            company_ids=[(6, 0, [cls.company_a.id])],
        )
        cls.user_solicitante_2 = new_test_user(
            cls.env, login="user_solicitante_2", name="Solicitante Dos",
            groups="payment_request.group_payment_request_user",
            company_ids=[(6, 0, [cls.company_a.id])],
        )
        cls.user_aprobador = new_test_user(
            cls.env, login="user_aprobador", name="Aprobador Uno",
            groups="payment_request.group_payment_request_approver",
            company_ids=[(6, 0, [cls.company_a.id])],
        )
        cls.user_tesoreria = new_test_user(
            cls.env, login="user_tesoreria", name="Tesorería Uno",
            groups="payment_request.group_payment_request_treasury",
            company_ids=[(6, 0, [cls.company_a.id])],
        )
        cls.user_company_b = new_test_user(
            cls.env, login="user_company_b", name="Usuario Compañía B",
            groups="payment_request.group_payment_request_user",
            company_id=cls.company_b.id,
            company_ids=[(6, 0, [cls.company_b.id])],
        )

        # Contabilidad mínima para postear pagos incluso en BD sin demo data
        cls._ensure_accounting_setup()

        cls.partner = cls.env["res.partner"].create({
            "name": "Proveedor Test",
            "vat": "J-123456789",
            "property_account_payable_id": cls.payable_account.id,
        })
        cls.usd_currency = cls.env.ref("base.USD")
        cls.ves_currency = cls.env.ref("base.VES")
        # VES viene inactiva en BDs sin demo: contabilizar con ella exige moneda activa
        cls.ves_currency.active = True

        # Nivel de Aprobación: >= $1000 asigna al aprobador
        cls.env["payment.approval.level"].create({
            "name": "Nivel Gerencia",
            "min_amount": 1000.0,
            "currency_id": cls.usd_currency.id,
            "approver_id": cls.user_aprobador.id,
            "company_id": cls.company_a.id,
        })

        # Tasas VES: ene-2026 1 USD = 10 Bs; jun-2026 1 USD = 20 Bs
        cls.env["res.currency.rate"].create([
            {"currency_id": cls.ves_currency.id, "rate": 10.0, "name": "2026-01-01"},
            {"currency_id": cls.ves_currency.id, "rate": 20.0, "name": "2026-06-01"},
        ])
        cls.journal_ves = cls.env["account.journal"].create({
            "name": "Banco VES Test",
            "type": "bank",
            "currency_id": cls.ves_currency.id,
        })
        (cls.journal_ves.inbound_payment_method_line_ids
         | cls.journal_ves.outbound_payment_method_line_ids).payment_account_id = cls.outstanding_account

    @classmethod
    def _ensure_accounting_setup(cls):
        """Garantiza cuentas y diario bancario para crear y contabilizar pagos,
        incluso en una BD creada sin demo data (sin plan contable instalado)."""
        company = cls.env.company
        cls.payable_account = cls.env["account.account"].search([
            ("account_type", "=", "liability_payable"),
            # Odoo 18: account.account filtro por company_ids (company_id ya no existe)
            ("company_ids", "in", [company.id]),
        ], limit=1)
        if not cls.payable_account:
            cls.payable_account = cls.env["account.account"].create({
                "code": "999900",
                "name": "Cuenta por Pagar Test",
                "account_type": "liability_payable",
            })
        cls.outstanding_account = cls.env["account.account"].search([
            ("account_type", "=", "asset_cash"),
            ("company_ids", "in", [company.id]),
        ], limit=1)
        if not cls.outstanding_account:
            cls.outstanding_account = cls.env["account.account"].create({
                "code": "999901",
                "name": "Cuenta Bancaria Test",
                "account_type": "asset_cash",
            })
        cls.journal = cls.env["account.journal"].search([
            ("type", "=", "bank"),
            ("company_id", "=", company.id),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env["account.journal"].create({
                "name": "Banco Test",
                "type": "bank",
                "company_id": company.id,
            })
        (cls.journal.inbound_payment_method_line_ids
         | cls.journal.outbound_payment_method_line_ids).payment_account_id = cls.outstanding_account

    def _create_request(self, amount=200.0, state="draft", currency=None, applicant=None):
        """Helper: crea una solicitud con valores deterministas para los tests."""
        return self.env["payment.request"].create({
            "partner_id": self.partner.id,
            "amount": amount,
            "concept": "Servicios varios",
            "currency_id": (currency or self.usd_currency).id,
            "state": state,
            "applicant_id": (applicant or self.user_solicitante).id,
            "assigned_approver_id": self.user_aprobador.id,
        })

    # ===================== Tramo A =====================

    def test_01_monto_positivo(self):
        """Tramo A: monto cero o negativo debe fallar."""
        with self.assertRaises(ValidationError):
            self.env["payment.request"].create({
                "partner_id": self.partner.id,
                "amount": 0.0,
                "concept": "Pago inválido",
            })

    def test_02_solicitante_no_puede_aprobar(self):
        """Tramo A: el solicitante no puede aprobar ni llamando al método."""
        req = self.env["payment.request"].with_user(self.user_solicitante).create({
            "partner_id": self.partner.id,
            "amount": 500.0,
            "concept": "Compra repuestos",
        })
        req.action_send()
        with self.assertRaises(AccessError):
            req.with_user(self.user_solicitante).action_approve()

    def test_03_flujo_completo_borrador_a_pagada(self):
        """Tramo A/B/C: flujo completo borrador → enviada → aprobada → pagada."""
        req = self.env["payment.request"].with_user(self.user_solicitante).create({
            "partner_id": self.partner.id,
            "amount": 500.0,
            "concept": "Flujo completo",
        })
        self.assertEqual(req.state, "draft")
        self.assertRegex(req.name, r"^SP/\d{4}/\d{4}$")

        req.action_send()
        self.assertEqual(req.state, "sent")

        req.with_user(req.assigned_approver_id).action_approve()
        self.assertEqual(req.state, "approved")
        self.assertEqual(req.approver_id, req.assigned_approver_id)
        self.assertTrue(req.approval_date)

        pay_wiz = self.env["payment.request.pay.wizard"].create({
            "request_id": req.id,
            "journal_id": self.journal.id,
            "payment_date": fields.Date.today(),
        })
        pay_wiz.action_confirm_payment()
        self.assertEqual(req.state, "paid")
        self.assertTrue(req.payment_id)

    def test_04_solicitud_enviada_no_se_edita(self):
        """Tramo A: una solicitud enviada no admite edición de sus datos."""
        req = self.env["payment.request"].with_user(self.user_solicitante).create({
            "partner_id": self.partner.id,
            "amount": 500.0,
            "concept": "Sin edición",
        })
        req.action_send()
        with self.assertRaises(UserError):
            req.write({"amount": 999.0})
        with self.assertRaises(UserError):
            req.write({"concept": "Concepto alterado"})

    def test_05_solicitante_solo_ve_las_suyas(self):
        """Tramo A: el solicitante solo ve sus propias solicitudes."""
        req_own = self.env["payment.request"].with_user(self.user_solicitante).create({
            "partner_id": self.partner.id,
            "amount": 100.0,
            "concept": "Mía",
        })
        req_other = self.env["payment.request"].with_user(self.user_solicitante_2).create({
            "partner_id": self.partner.id,
            "amount": 100.0,
            "concept": "Ajena",
        })
        visible = self.env["payment.request"].with_user(self.user_solicitante).search([])
        self.assertIn(req_own, visible)
        self.assertNotIn(req_other, visible)

    # ===================== Tramo B =====================

    def test_06_asignacion_de_aprobador_y_actividad(self):
        """Tramo B: el monto alto asigna al aprobador del nivel y crea actividad."""
        req = self.env["payment.request"].with_user(self.user_solicitante).create({
            "partner_id": self.partner.id,
            "amount": 1500.0,
            "concept": "Pago de maquinaria",
        })
        req.action_send()
        self.assertEqual(req.state, "sent")
        self.assertEqual(req.assigned_approver_id, self.user_aprobador)

        activities = self.env["mail.activity"].search([
            ("res_model", "=", "payment.request"),
            ("res_id", "=", req.id),
        ])
        self.assertTrue(activities)
        self.assertEqual(activities.user_id, self.user_aprobador)

    def test_07_solo_aprobador_asignado(self):
        """Tramo B: solo el aprobador asignado puede aprobar; una segunda
        aprobación (doble click) también queda bloqueada."""
        req = self._create_request(state="sent")
        with self.assertRaises(UserError):
            req.with_user(self.user_tesoreria).action_approve()

        req.with_user(self.user_aprobador).action_approve()
        self.assertEqual(req.state, "approved")

        with self.assertRaises(UserError):
            req.with_user(self.user_aprobador).action_approve()

    def test_08_rechazo_con_motivo_en_chatter(self):
        """Tramo B: el rechazo exige motivo y queda publicado en el chatter."""
        req = self._create_request(state="sent")
        wiz = self.env["payment.request.reject.wizard"].create({
            "request_id": req.id,
            "reject_reason": "Falta presupuesto",
        })
        wiz.action_reject()
        self.assertEqual(req.state, "rejected")
        bodies = req.message_ids.mapped("body")
        self.assertTrue(any("Falta presupuesto" in body for body in bodies))
        # Odoo 18 escapa los cuerpos str en message_post: con Markup la etiqueta debe quedar real
        reject_body = next(body for body in bodies if "Falta presupuesto" in body)
        self.assertIn("<b>", reject_body)

    def test_09_pdf_muestra_quien_aprobo_y_cuando(self):
        """Tramo B: el PDF muestra quién aprobó y cuándo."""
        req = self._create_request(state="sent")
        req.with_user(self.user_aprobador).action_approve()

        html, _err = self.env["ir.actions.report"]._render_qweb_html(
            "payment_request.action_report_payment_request", req.ids)
        content = html.decode() if isinstance(html, bytes) else "".join(html)
        self.assertIn(self.user_aprobador.name, content)
        self.assertIn(req.name, content)
        self.assertIn("Fecha de Aprobación", content)
        self.assertIn(str(req.approval_date.year), content)

    def test_10_no_se_puede_pagar_dos_veces(self):
        """Tramo B: una solicitud aprobada no se puede pagar dos veces."""
        req = self._create_request(amount=200.0, state="approved")
        pay_wiz = self.env["payment.request.pay.wizard"].create({
            "request_id": req.id,
            "journal_id": self.journal.id,
            "payment_date": fields.Date.today(),
        })
        pay_wiz.action_confirm_payment()
        self.assertEqual(req.state, "paid")
        self.assertTrue(req.payment_id)
        # Odoo 18 escapa los cuerpos str en message_post: con Markup el enlace debe quedar real
        payment_body = next(
            body for body in req.message_ids.mapped("body") if "Pago contable registrado" in body
        )
        self.assertIn("<a href", payment_body)

        pay_wiz_dup = self.env["payment.request.pay.wizard"].create({
            "request_id": req.id,
            "journal_id": self.journal.id,
            "payment_date": fields.Date.today(),
        })
        with self.assertRaises(UserError):
            pay_wiz_dup.action_confirm_payment()

    # ===================== Tramo C =====================

    def test_11_conversion_usd_ves_a_tasa_de_la_fecha(self):
        """Tramo C: el pago en diario VES usa la tasa de la fecha de pago."""
        req = self._create_request(amount=100.0, state="approved", currency=self.usd_currency)

        wiz_late = self.env["payment.request.pay.wizard"].create({
            "request_id": req.id,
            "journal_id": self.journal_ves.id,
            "payment_date": date(2026, 6, 1),
        })
        self.assertEqual(wiz_late.journal_currency_id, self.ves_currency)
        self.assertAlmostEqual(wiz_late.amount_in_journal_currency, 2000.0)

        wiz_early = self.env["payment.request.pay.wizard"].create({
            "request_id": req.id,
            "journal_id": self.journal_ves.id,
            "payment_date": date(2026, 1, 15),
        })
        self.assertAlmostEqual(wiz_early.amount_in_journal_currency, 1000.0)

        # Contabilizar el pago: el monto y la moneda del pago son los de VES a la tasa del día
        wiz_late.action_confirm_payment()
        self.assertEqual(req.state, "paid")
        self.assertEqual(req.payment_id.currency_id, self.ves_currency)
        self.assertAlmostEqual(req.payment_id.amount, 2000.0)

    def test_12_fallo_de_pago_no_deja_solicitud_pagada(self):
        """Tramo C: si la contabilización del pago falla, la solicitud NO
        queda en estado pagada."""
        req = self._create_request(amount=100.0, state="approved")
        pay_wiz = self.env["payment.request.pay.wizard"].create({
            "request_id": req.id,
            "journal_id": self.journal.id,
            "payment_date": fields.Date.today(),
        })
        payment_model = self.env.registry["account.payment"]
        with patch.object(payment_model, "action_post", side_effect=UserError("Fallo simulado del asiento")):
            with self.assertRaises(UserError):
                pay_wiz.action_confirm_payment()

        self.assertEqual(req.state, "approved")
        self.assertFalse(req.payment_id)

    def test_13_aislamiento_multi_compania(self):
        """Tramo C: un usuario de otra compañía no ve las solicitudes de la primera."""
        req_a = self._create_request(
            amount=100.0,
            state="draft",
            # solicitante de la compañía B: solo la regla de compañía puede excluirlo
            applicant=self.user_company_b,
        )
        self.assertEqual(req_a.company_id, self.company_a)
        visible = self.env["payment.request"].with_user(self.user_company_b).search([])
        self.assertNotIn(req_a, visible)
