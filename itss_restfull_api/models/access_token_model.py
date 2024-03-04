import hashlib
import os
from datetime import datetime, timedelta
from odoo import api, fields, models
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as df


def random_token(length=200):
    return f"{str(hashlib.sha256(os.urandom(length)).hexdigest())}"


class APITokens(models.Model):
    _name = 'api.tokens'

    token = fields.Char(
        string="Token",
        required=True
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        store=True
    )

    token_expiry_date = fields.Datetime(
        string="Token Expiry Date",
        required=True
    )

    def find_or_create_token(self, user_id=None, create=False):
        user_id = self.env.user.id if not user_id else user_id

        access_token = self.env["api.tokens"].sudo().search([("user_id", "=", user_id)], order="id DESC", limit=1)

        access_token = None if access_token.exists() and access_token.has_expired() else access_token

        if not access_token and create:
            token_expiry_date = datetime.now() + timedelta(days=1)
            vals = {
                "user_id": user_id,
                "token_expiry_date": token_expiry_date.strftime(df),
                "token": random_token(),
            }
            access_token = self.env['api.tokens'].sudo().create(vals)

        if not access_token:
            return None

        return access_token.token

    def has_expired(self):
        self.ensure_one()
        return datetime.now() > fields.Datetime.from_string(self.token_expiry_date)

    def is_valid(self):
        self.ensure_one()
        return not self.has_expired()
