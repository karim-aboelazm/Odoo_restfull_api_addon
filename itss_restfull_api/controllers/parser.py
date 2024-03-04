from pypeg2 import name, csl, List, parse, optional, contiguous, word

class IncludedField(List):
    grammar = name()

class ExcludedField(List):
    grammar = contiguous('-', name())

class AllFields(str):
    grammar = '*'

class Argument(List):
    grammar = name(), ':', word

    @property
    def value(self): return self[0]

class Arguments(List):
    grammar = optional(csl([Argument]))

class ArgumentsBlock(List):
    grammar = optional('(', Arguments, ')')

    @property
    def arguments(self): return [] if self[0] is None else self[0]

class ParentField(List):
    @property
    def name(self): return self[0].name

    @property
    def block(self): return self[1]

class BlockBody(List):
    grammar = optional(csl([ParentField, IncludedField, ExcludedField, AllFields]))

class Block(List):
    grammar = ArgumentsBlock, '{', BlockBody, '}'

    @property
    def arguments(self): return self[0].arguments

    @property
    def body(self): return self[1]


ParentField.grammar = IncludedField, Block


class Parser:
    def __init__(self, query):
        self._query = query

    def get_parsed(self):
        return self._transform_block(parse(self._query, Block))

    def _transform_block(self, block):
        fields = {"include": [], "exclude": [], "arguments": {}}
        for argument in block.arguments:
            fields['arguments'].update({str(argument.name): argument.value})

        for field in block.body:
            field = self._transform_field(field)
            if isinstance(field, dict):
                fields["include"].append(field)
            elif isinstance(field, IncludedField):
                fields["include"].append(str(field.name))
            elif isinstance(field, ExcludedField):
                fields["exclude"].append(str(field.name))
            elif isinstance(field, AllFields):
                fields["include"].append("*")

        if fields["exclude"]:
            add_include_all_operator = True
            for field in fields["include"]:
                if field == "*":
                    add_include_all_operator = False
                    continue
                if isinstance(field, str):
                    raise ValueError("Can not include and exclude fields on the same field level")
            if add_include_all_operator:
                fields["include"].append("*")
        return fields

    def _transform_field(self, field):
        if isinstance(field, ParentField):
            return self._transform_parent_field(field)
        elif isinstance(field, (IncludedField, ExcludedField, AllFields)):
            return field

    def _transform_parent_field(self, parent_field):
        return {str(parent_field.name): self._transform_block(parent_field.block)}
