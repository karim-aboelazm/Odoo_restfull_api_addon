from odoo import api, fields, models

class UserAccessToken(models.Model):
    _inherit = 'res.users'

    token_ids = fields.One2many(
        comodel_name="api.tokens",
        inverse_name="user_id",
        string="Access Tokens"
    )

    @api.model
    def get_user_data(self, uid):
        user = self.env['res.users'].browse(int(uid))
        access_token = self.env["api.tokens"].find_or_create_token(user_id=user.id, create=True)
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        user_data = {
            'id': user.id,
            'name': user.name,
            'email': user.login,
            'api_token': access_token,
        }
        return user_data
