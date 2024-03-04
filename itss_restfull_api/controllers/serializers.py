# -*- coding: utf-8 -*-
import itertools
import datetime
from itertools import chain
from .parser import Parser

DATATIME_FORMATS = "%Y-%m-%d %H:%M:%S"
DATE_FORMATS = "%Y-%m-%d"
TIME_FORMATS = "%H:%M:%S"


class Serializer(object):
    def __init__(self, record, query="{*}", many=False):
        self.many = many
        self._record = record
        self._raw_query = query
        super().__init__()

    def get_parsed_restql_query(self):
        parser = Parser(self._raw_query)
        try:
            return parser.get_parsed()
        except SyntaxError as e:
            raise SyntaxError(f"QuerySyntaxError: {e.msg} on {e.text}") from None
        except ValueError as e:
            raise ValueError(f"QueryFormatError: {str(e)}") from None

    @property
    def data(self):
        parsed_restql_query = self.get_parsed_restql_query()
        if self.many:
            return [self.serialize(rec, parsed_restql_query) for rec in self._record]
        return self.serialize(self._record, parsed_restql_query)

    @classmethod
    def build_flat_field(cls, rec, field_name):
        if field_name not in rec.fields_get_keys():
            raise LookupError(f"{field_name} field is not found")
        field_type = rec.fields_get(field_name).get(field_name).get('type')
        if field_type in ['one2many', 'many2many']:
            return {field_name: [record.id for record in rec[field_name]]}
        elif field_type in ['many2one']:
            return {field_name: rec[field_name].id}
        elif field_type == 'datetime' and rec[field_name]:
            return {field_name: rec[field_name].strftime(DATATIME_FORMATS)}
        elif field_type == 'date' and rec[field_name]:
            return {field_name: rec[field_name].strftime(DATE_FORMATS)}
        elif field_type == 'time' and rec[field_name]:
            return {field_name: rec[field_name].strftime(TIME_FORMATS)}
        elif field_type == "binary" and rec[field_name]:
            return {field_name: rec[field_name]}
        else:
            return {field_name: rec[field_name]}

    @classmethod
    def build_nested_field(cls, rec, field_name, nested_parsed_query):
        if field_name not in rec.fields_get_keys():
            raise LookupError(f"{field_name} field is not found")
        field_type = rec.fields_get(field_name).get(field_name).get('type')
        if field_type in ['one2many', 'many2many']:
            return {field_name: [cls.serialize(record, nested_parsed_query) for record in rec[field_name]]}
        elif field_type in ['many2one']:
            return {field_name: cls.serialize(rec[field_name], nested_parsed_query)}
        else:
            raise ValueError(f"{field_name} is not a nested field")

    @classmethod
    def serialize(cls, rec, parsed_query):
        data = {}
        if parsed_query["exclude"]:
            all_fields = rec.fields_get_keys()
            for field in parsed_query["include"]:
                if field == "*":
                    continue
                for nested_field, nested_parsed_query in field.items():
                    data.update(cls.build_nested_field(rec, nested_field, nested_parsed_query))

            flat_fields = set(all_fields).symmetric_difference(set(parsed_query['exclude']))
            for field in flat_fields:
                data.update(cls.build_flat_field(rec, field))

        elif parsed_query["include"]:
            all_fields = rec.fields_get_keys()
            if "*" in parsed_query['include']:
                parsed_query['include'] = filter(lambda item: item != "*", parsed_query['include'])
                fields = chain(parsed_query['include'], all_fields)
                parsed_query['include'] = reversed(list(fields))

            for field in parsed_query["include"]:
                if isinstance(field, dict):
                    for nested_field, nested_parsed_query in field.items():
                        data.update(cls.build_nested_field(rec, nested_field, nested_parsed_query))
                else:
                    data.update(cls.build_flat_field(rec, field))
        else:
            return {}
        return data
