# -*- coding: utf-8 -*-

# Used Library Imports
import subprocess
try:
    import magic
    import tempfile
    import pandas as pd
    from PIL import Image
    import fitz
except ImportError:
    lib_list = ['python-magic', 'pandas', 'Pillow', 'PyMuPDF', 'openpyxl']
    for lib in lib_list:
        subprocess.run(['pip', 'install', lib], check=True)
import base64
import functools
import hashlib
import io
import json
import os
import requests
from odoo import api, models, http, _, exceptions
from odoo.http import request
from .serializers import Serializer
import werkzeug.wrappers as w


# ==============================================================================================================#
# ====================================   Valid Responses Method   ==============================================#
# ==============================================================================================================#
def valid_response(data=None, message: str = None, code=200):
    result = {
        "code": str(code),
        "status": "true",
        "message": f"{message}" if message is not None else "response is done successfully",
        "result": data if data is not None else {}
    }
    return w.Response(status=str(code), content_type="application/json; charset=utf-8", response=json.dumps(result))


# ==============================================================================================================#
# ===================================   Invalid Responses Method   =============================================#
# ==============================================================================================================#
def invalid_response(message: str = None, code=401):
    result = {
        "code": str(code),
        "status": "false",
        "message": f"{message}" if message is not None else "response is not done successfully",
        "result": {}
    }
    return w.Response(status=str(code), content_type="application/json; charset=utf-8", response=json.dumps(result))


# ==============================================================================================================#
# ================================   Validate Access Token Decorator  ==========================================#
# ==============================================================================================================#
def validate_access_token(func):
    @functools.wraps(func)
    def wrap(self, *args, **kwargs):
        auth_header = request.httprequest.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return invalid_response("missing or invalid access token in request header", 401)

        TOKEN = auth_header[len("Bearer "):]
        API_MODEL = "api.tokens"
        API_DOMAIN = [("token", "ilike", TOKEN)]  # noqa

        access_token_data = request.env[API_MODEL].sudo().search(API_DOMAIN, limit=1, order="id DESC")

        if access_token_data.find_or_create_token(user_id=access_token_data.user_id.id) != TOKEN:
            return invalid_response("token seems to have expired or invalid", 401)

        request.session.uid = access_token_data.user_id.id
        request.env.uid = access_token_data.user_id.id

        return func(self, *args, **kwargs)  # noqa

    return wrap

# ==============================================================================================================#
# =================================   Start Restful Api Odoo Class   ===========================================#
# ==============================================================================================================#
class ItssOdooAPI(http.Controller):
    urls = ['/api/authenticate/',
            '/api/<string:model>/',
            '/api/<string:model>/<int:rec_id>/',
            '/api/<string:model>/<string:function>/',
            '/api/<string:model>/<int:rec_id>/<string:function>/',
            '/api/<string:model>/<int:rec_id>/<string:field>']

    # ==========================================================================================================#
    # ============ Creating New Access Token Request For `User` Using <username>,<password> ====================#
    # ==========================================================================================================#
    @http.route(urls[0], type='http', auth='none', methods=["POST"], csrf=False, save_session=False, cors='*')
    def user_access_token(self):
        payload = json.loads(request.httprequest.data.decode())
        try:
            login = payload["login"]
        except KeyError:
            return invalid_response('login is required.', code=403)
        try:
            password = payload["password"]
        except KeyError:
            return invalid_response('password is required.', code=403)

        if not request.env['res.users'].sudo().search([('login', 'ilike', login)]):  # noqa
            return invalid_response('login is wrong.', code=403)
        try:
            request.session.authenticate(request.env.cr.dbname, login, password)
        except exceptions.AccessDenied:
            return invalid_response('password is wrong.', code=403)
        try:
            return valid_response(request.env.user.get_user_data(int(request.env.user.id)))
        except SyntaxError as e:
            return invalid_response(e.msg)

    # ==========================================================================================================#
    # ========  Reading Any Model data using <model_name>,<domain>,<limits>,<order>,<response_pattern> =========#
    # ==========================================================================================================#
    @http.route(urls[1], type='http', auth='user', methods=['GET'], csrf=False, save_session=False, cors='*')
    def read_model_records_data(self, model):
        try:
            request.env[model].search([])
        except KeyError:
            return invalid_response(f"The model {model} does not exist.")

        payload = json.loads(request.httprequest.data)

        pattern = payload["pattern"] if "pattern" in payload else "{*}"

        orders = payload["order"] if "order" in payload else ""

        domain = payload["domain"] if "domain" in payload else []

        limit = int(payload["limit"]) if "limit" in payload else None

        records = request.env[model].search(domain, order=orders, limit=limit)

        try:
            serializer = Serializer(records, pattern, many=True)
            return valid_response(serializer.data)
        except (SyntaxError, LookupError) as e:
            if hasattr(e, 'msg'):
                return invalid_response(e.msg)
            else:
                return invalid_response(str(e))

    # ==========================================================================================================#
    # =======  Creating Any Model record data using <model_name>,<fields>,<related_fields>,<context> ===========#
    # ==========================================================================================================#
    @http.route(urls[1], type='http', auth="user", methods=['POST'], csrf=False, save_session=False, cors='*')
    def create_model_records_data(self, model):
        payload = json.loads(request.httprequest.data.decode())
        try:
            model_to_post = request.env[model]
        except KeyError:
            return invalid_response(f"The model {model} does not exist.")

        try:
            data = payload.get('fields')
        except KeyError:
            return invalid_response("`fields` parameter is not found on POST request body")

        context = payload["context"] if "context" in payload else {}

        record = model_to_post.with_context(**context).create(data)

        pattern = payload['pattern'] if 'pattern' in payload else "{id,name}"

        if "related_fields" in payload:
            additional_data = payload.get("related_fields")
            for k, v in additional_data.items():
                record.write({k: [(0, 0, v)]})
        try:
            serializer = Serializer(record, pattern, many=True)
            return valid_response(serializer.data)
        except (SyntaxError, LookupError) as e:
            if hasattr(e, 'msg'):
                return invalid_response(e.msg)
            else:
                return invalid_response(str(e))

    # ==========================================================================================================#
    # =====  Updating Any Model record data using <model_name>,<domain>,<fields>,<related_fields>,<context> ====#
    # ==========================================================================================================#
    @http.route(urls[1], type='http', auth="user", methods=['PUT'], csrf=False, save_session=False, cors='*')
    def update_model_records_data(self, model):
        payload = json.loads(request.httprequest.data.decode())
        domain = payload['domain']
        if not domain:
            return invalid_response("their is not a valid domain")
        try:
            data = payload.get('fields')
        except KeyError:
            return invalid_response("`data` parameter is not found on PUT request body")
        try:
            model_to_put = request.env[model]
        except KeyError:
            return invalid_response(f"The model `{model}` does not exist.")

        context = payload.get("context") if "context" in payload else {}
        records = model_to_put.with_context(**context).search(domain)
        additional_data = None
        if "related_fields" in payload:
            additional_data = payload.get("related_fields")
            for field in additional_data:
                if isinstance(additional_data[field], dict):
                    operations = []
                    for operation in additional_data[field]:
                        if operation == "push":
                            operations.extend((4, rec_id, _) for rec_id in additional_data[field].get("push"))
                        elif operation == "pop":
                            operations.extend((3, rec_id, _) for rec_id in additional_data[field].get("pop"))
                        elif operation == "delete":
                            operations.extend((2, rec_id, _) for rec_id in additional_data[field].get("delete"))
                        elif operation == "update":
                            operations.extend(
                                (1, int(rec[0]), dict(rec[1])) for rec in additional_data[field].get("update"))
                        elif operation == "append":
                            operations.extend((0, 0, rec) for rec in additional_data[field].get("append"))
                        else:
                            additional_data[field].pop(operation)

                    additional_data[field] = operations
                elif isinstance(additional_data[field], list):
                    additional_data[field] = [(6, _, additional_data[field])]
                else:
                    pass
        try:
            for rec in records:
                rec.write(data)
                if additional_data:
                    rec.write(additional_data)
            return valid_response(message="records is updated successfully.")
        except Exception as e:
            return valid_response(str(e))

    # ==========================================================================================================#
    # ======================  Deleting Any Model records data using <model_name>,<domain>  =====================#
    # ==========================================================================================================#
    @http.route(urls[1], type='http', auth="user", methods=['DELETE'], csrf=False, save_session=False, cors='*')
    def delete_model_records_data(self, model):
        payload = json.loads(request.httprequest.data.decode())
        try:
            model_to_del_rec = request.env[model]
        except KeyError:
            return invalid_response(f"The model `{model}` does not exist.")

        if 'domain' not in payload:
            return invalid_response("their is not a valid domain")

        try:
            records = model_to_del_rec.search(payload["domain"])
            for rec in records:
                rec.unlink()
            return valid_response(message="records deleted successfully")
        except Exception as e:
            return invalid_response(str(e))

    # ==========================================================================================================#
    # =====  Updating Any Model record data using <model_name>,<rec_id>,<fields>,<related_fields>,<context> ====#
    # ==========================================================================================================#
    @http.route(urls[2], type='http', auth="user", methods=['PUT'], csrf=False, save_session=False, cors='*')
    def update_model_record_data(self, model, rec_id):
        payload = json.loads(request.httprequest.data.decode())
        try:
            data = payload.get('fields')
        except KeyError:
            return invalid_response("`data` parameter is not found on PUT request body")
        try:
            model_to_put = request.env[model]
        except KeyError:
            return invalid_response(f"The model `{model}` does not exist.")

        context = payload.get("context") if "context" in payload else {}
        records = model_to_put.with_context(**context).browse(rec_id)

        additional_data = None
        if "related_fields" in payload:
            additional_data = payload.get("related_fields")
            for field in additional_data:
                if isinstance(additional_data[field], dict):
                    operations = []
                    for operation in additional_data[field]:
                        if operation == "push":
                            operations.extend((4, rec_id, _) for rec_id in additional_data[field].get("push"))
                        elif operation == "pop":
                            operations.extend((3, rec_id, _) for rec_id in additional_data[field].get("pop"))
                        elif operation == "delete":
                            operations.extend((2, rec_id, _) for rec_id in additional_data[field].get("delete"))
                        elif operation == "update":
                            operations.extend(
                                (1, int(rec[0]), dict(rec[1])) for rec in additional_data[field].get("update"))
                        elif operation == "append":
                            operations.extend((0, 0, rec) for rec in additional_data[field].get("append"))
                        else:
                            additional_data[field].pop(operation)

                    additional_data[field] = operations
                elif isinstance(additional_data[field], list):
                    additional_data[field] = [(6, _, additional_data[field])]
                else:
                    pass
        try:
            for rec in records:
                rec.write(data)
                if additional_data:
                    rec.write(additional_data)
            return valid_response(message="records is updated successfully.")
        except Exception as e:
            return valid_response(str(e))

    # ==========================================================================================================#
    # ======================  Deleting Any Model records data using <model_name>,<rec_id>  =====================#
    # ==========================================================================================================#
    @http.route(urls[2], type='http', auth="user", methods=['DELETE'], csrf=False, save_session=False, cors='*')
    def delete_model_record_data(self, model, rec_id):
        try:
            model_to_del_rec = request.env[model]
        except KeyError:
            return invalid_response(f"The model `{model}` does not exist.")
        try:
            rec = model_to_del_rec.browse(int(rec_id))
            rec.unlink()
            return valid_response(message="record deleted successfully")
        except Exception as e:
            return invalid_response(str(e))

    # ==========================================================================================================#
    # ========== Execute External Methods In Any Model Using <model_name>,<method_name>,<args>,<kwargs> ========#
    # ==========================================================================================================#
    @http.route(urls[3], type='http', auth='user', methods=["POST"], csrf=False, save_session=False, cors='*')
    def call_model_external_method(self, model, function):
        payload = json.loads(request.httprequest.data.decode())
        args = payload["args"] if "args" in payload else []
        kwargs = payload["kwargs"] if "kwargs" in payload else {}
        try:
            get_model = request.env[model]
            result = getattr(get_model, function)(*args, **kwargs)
            if isinstance(result, models.Model):
                serializer = Serializer(result, "{id,name}", many=True)
                return valid_response(serializer.data)
            return valid_response(result)
        except Exception as e:
            return invalid_response(str(e))

    # ==========================================================================================================#
    # = Execute External Methods In Any Model Record Using <model_name>,<rec_id>,<method_name>,<args>,<kwargs>  #
    # ==========================================================================================================#
    @http.route(urls[4], type='http', auth='user', methods=["POST"], csrf=False, save_session=False, cors='*')
    def call_record_external_method(self, model, rec_id, function):
        payload = json.loads(request.httprequest.data.decode())
        args = payload["args"] if "args" in payload else []
        kwargs = payload["kwargs"] if "kwargs" in payload else {}
        obj = request.env[model].browse(rec_id).ensure_one()
        try:
            result = getattr(obj, function)(*args, **kwargs)
            return valid_response(result)
        except Exception as e:
            return invalid_response(str(e))

    # ===========================================================================================================#
    # ====== Read Any Binary Field And Can Downloaded It Using <model_name>,<rec_id>,<field_name>,<download> ====#
    # ===========================================================================================================#
    @http.route(urls[5], type='http', auth="user", methods=['GET'], csrf=False, save_session=False, cors='*')
    def read_or_download_binary_data(self, model, rec_id, field):
        payload = json.loads(request.httprequest.data.decode())
        try:
            request.env[model]
        except KeyError:
            return invalid_response(f"The model {model} does not exist.")
        rec = request.env[model].browse(rec_id).ensure_one()
        if rec.exists():
            src = getattr(rec, field).decode('utf-8')
            if src:
                src = src
                binary_stream = io.BytesIO(base64.b64decode(src))
                mime = magic.Magic()
                file_type = mime.from_buffer(binary_stream.read(1024))
                binary_stream.seek(0)
                desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                if 'download' in payload and payload.get('download') in ["1", "true", "True"]:
                    if "image" in file_type:
                        image = Image.open(binary_stream)
                        image_path = os.path.join(desktop_path, "output.jpg")
                        image.save(image_path)
                        image.show()
                    elif "pdf" in file_type:
                        pdf_document = fitz.open("pdf", binary_stream.read())
                        for page_number in range(pdf_document.page_count):
                            page = pdf_document.load_page(page_number)
                            image = page.get_pixmap()
                            image_path = os.path.join(desktop_path, f"output_page_{page_number + 1}.png")
                            image.save(image_path)
                        pdf_document.close()
                    elif "spreadsheet" in file_type:
                        excel_data = pd.read_excel(binary_stream, engine="openpyxl")
                        xlsx_path = os.path.join(desktop_path, "output.xlsx")
                        excel_data.to_excel(xlsx_path, index=False)
        else:
            src = ""
        return valid_response(data={f"{field}": src})

# ==============================================================================================================#
# ==================================   End Restful Api Odoo Class   ============================================#
# ==============================================================================================================#
