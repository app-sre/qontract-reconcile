# type: ignore
# pylint: skip-file
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from graphql import (
    FieldNode,
    GraphQLList,
    GraphQLNonNull,
    GraphQLOutputType,
    GraphQLScalarType,
    GraphQLSchema,
    InlineFragmentNode,
    OperationDefinitionNode,
    Visitor,
    TypeInfo,
    TypeInfoVisitor,
    visit,
    parse,
    get_operation_ast,
    validate,
)

from code_generator.mapper import (
    graphql_primitive_to_python,
    graphql_field_name_to_python,
)


INDENT = "    "


@dataclass
class ParsedNode:
    parent: Optional[ParsedNode]
    fields: list[ParsedNode]
    parsed_type: ParsedFieldType

    def class_code_string(self) -> str:
        return ""


@dataclass
class ParsedInlineFragmentNode(ParsedNode):
    def class_code_string(self) -> str:
        if self.parsed_type.is_primitive:
            return ""

        lines = ["\n\n"]
        lines.append(f"class {self.parsed_type.unwrapped_python_type}(BaseModel):")
        for parent_field in self.parent.fields:
            if isinstance(parent_field, ParsedClassNode):
                lines.append(
                    f'{INDENT}{parent_field.py_key}: {parent_field.field_type()} = Field(..., alias="{parent_field.gql_key}")'
                )
        for field in self.fields:
            if isinstance(field, ParsedClassNode):
                lines.append(
                    f'{INDENT}{field.py_key}: {field.field_type()} = Field(..., alias="{field.gql_key}")'
                )

        # https://pydantic-docs.helpmanual.io/usage/model_config/#smart-union
        # https://stackoverflow.com/a/69705356/4478420
        lines.append("")
        lines.append(f"{INDENT}class Config:")
        lines.append(f"{INDENT}{INDENT}smart_union = True")
        lines.append(f"{INDENT}{INDENT}extra = 'forbid'")

        return "\n".join(lines)


@dataclass
class ParsedClassNode(ParsedNode):
    gql_key: str
    py_key: str

    def class_code_string(self) -> str:
        if self.parsed_type.is_primitive:
            return ""

        lines = ["\n\n"]
        lines.append(f"class {self.parsed_type.unwrapped_python_type}(BaseModel):")
        for field in self.fields:
            if isinstance(field, ParsedClassNode):
                lines.append(
                    f'{INDENT}{field.py_key}: {field.field_type()} = Field(..., alias="{field.gql_key}")'
                )

        # https://pydantic-docs.helpmanual.io/usage/model_config/#smart-union
        # https://stackoverflow.com/a/69705356/4478420
        lines.append("")
        lines.append(f"{INDENT}class Config:")
        lines.append(f"{INDENT}{INDENT}smart_union = True")
        lines.append(f"{INDENT}{INDENT}extra = 'forbid'")

        return "\n".join(lines)

    def field_type(self) -> str:
        unions: list[str] = []
        # TODO: sorting does not need to happen on each call
        self.fields.sort(key=self._type_significance, reverse=True)
        for field in self.fields:
            if isinstance(field, ParsedInlineFragmentNode):
                unions.append(field.parsed_type.unwrapped_python_type)
        if len(unions) > 0:
            unions.append(self.parsed_type.unwrapped_python_type)
            return self.parsed_type.wrapped_python_type.replace(
                self.parsed_type.unwrapped_python_type, f"Union[{', '.join(unions)}]"
            )
        return self.parsed_type.wrapped_python_type

    def _type_significance(self, node: ParsedInlineFragmentNode) -> int:
        """
        Pydantic does best-effort matching on Unions.
        Declare most significant type first.
        This, smart_union and disallowing extra fields gives high confidence in matching.

        https://pydantic-docs.helpmanual.io/usage/types/#unions
        """
        return len(node.fields)


@dataclass
class ParsedOperationNode(ParsedNode):
    def class_code_string(self) -> str:
        lines = ["\n\n"]
        lines.append(f"class {self.parsed_type.unwrapped_python_type}Query(BaseModel):")
        for field in self.fields:
            if isinstance(field, ParsedClassNode):
                lines.append(
                    f'{INDENT}{field.py_key}: {field.field_type()} = Field(..., alias="{field.gql_key}")'
                )

        # https://pydantic-docs.helpmanual.io/usage/model_config/#smart-union
        # https://stackoverflow.com/a/69705356/4478420
        lines.append("")
        lines.append(f"{INDENT}class Config:")
        lines.append(f"{INDENT}{INDENT}smart_union = True")
        lines.append(f"{INDENT}{INDENT}extra = 'forbid'")

        return "\n".join(lines)


@dataclass
class ParsedFieldType:
    unwrapped_python_type: str
    wrapped_python_type: str
    is_primitive: bool


class FieldToTypeMatcherVisitor(Visitor):
    def __init__(self, schema: GraphQLSchema, type_info: TypeInfo, query: str):
        # These are required for GQL Visitor to do its magic
        Visitor.__init__(self)
        self.schema = schema
        self.type_info = type_info
        self.query = query

        # These are our custom fields
        self.parsed = ParsedNode(
            parent=None,
            fields=[],
            parsed_type=ParsedFieldType(
                unwrapped_python_type="",
                wrapped_python_type="",
                is_primitive=False,
            ),
        )
        self.parent = self.parsed
        self.deduplication_cache: set[str] = set()

    # GQL mandatory functions
    def enter(self, node, *_):
        pass

    def leave(self, node, *_):
        pass

    def enter_inline_fragment(self, node: InlineFragmentNode, *_):
        graphql_type = self.type_info.get_type()
        field_type = self._parse_type(graphql_type=graphql_type)
        current = ParsedInlineFragmentNode(
            fields=[],
            parent=self.parent,
            parsed_type=field_type,
        )
        self.parent.fields.append(current)
        self.parent = current

    def leave_inline_fragment(self, node: InlineFragmentNode, *_):
        self.parent = self.parent.parent if self.parent else self.parent

    def enter_operation_definition(self, node: OperationDefinitionNode, *_):
        current = ParsedOperationNode(
            parent=self.parent,
            fields=[],
            parsed_type=ParsedFieldType(
                unwrapped_python_type=node.name.value,
                wrapped_python_type=f"Optional[list[{node.name.value}]]",
                is_primitive=False,
            ),
        )
        self.parent.fields.append(current)
        self.parent = current

    def leave_operation_definition(self, node: OperationDefinitionNode, *_):
        self.parent = self.parent.parent if self.parent else self.parent

    def enter_field(self, node: FieldNode, *_):
        graphql_type: GraphQLOutputType = self.type_info.get_type()
        field_type = self._parse_type(graphql_type=graphql_type)
        py_key = graphql_field_name_to_python(node.name.value)
        gql_key = node.alias.value if node.alias else node.name.value
        current = ParsedClassNode(
            fields=[],
            parent=self.parent,
            parsed_type=field_type,
            py_key=py_key,
            gql_key=gql_key,
        )

        self.parent.fields.append(current)
        self.parent = current

    def leave_field(self, node: FieldNode, *_):
        self.parent = self.parent.parent if self.parent else self.parent

    # Custom Functions
    def _parse_type(self, graphql_type: GraphQLOutputType) -> ParsedFieldType:
        is_optional = True
        if isinstance(graphql_type, GraphQLNonNull):
            is_optional = False
            graphql_type = graphql_type.of_type

        is_list = False
        if isinstance(graphql_type, GraphQLList):
            is_list = True
            graphql_type = graphql_type.of_type

        needs_further_unwrapping = isinstance(
            graphql_type, GraphQLNonNull
        ) or isinstance(graphql_type, GraphQLList)
        parsed_of_type = None
        if needs_further_unwrapping:
            parsed_of_type = self._parse_type(graphql_type=graphql_type)

        unwrapped_type = (
            self._to_python_type(graphql_type)
            if not parsed_of_type
            else parsed_of_type.unwrapped_python_type
        )
        wrapped_type = (
            unwrapped_type if not parsed_of_type else parsed_of_type.wrapped_python_type
        )
        is_primitive = (
            isinstance(graphql_type, GraphQLScalarType)
            if not parsed_of_type
            else parsed_of_type.is_primitive
        )

        if is_optional and is_list:
            wrapped_type = f"Optional[list[{wrapped_type}]]"
        elif is_optional:
            wrapped_type = f"Optional[{wrapped_type}]"
        elif is_list:
            wrapped_type = f"list[{wrapped_type}]"

        return ParsedFieldType(
            unwrapped_python_type=unwrapped_type,
            wrapped_python_type=wrapped_type,
            is_primitive=is_primitive,
        )

    def _to_python_type(self, graphql_type: GraphQLOutputType) -> str:
        if isinstance(graphql_type, GraphQLScalarType):
            return graphql_primitive_to_python(graphql_type=graphql_type)
        else:
            cur = self.parent.parent
            class_name = str(graphql_type).replace("_", "")
            class_name = f"{class_name[:-2]}V{class_name[-1]}"
            while cur and cur.parent and class_name in self.deduplication_cache:
                class_name = f"{cur.parsed_type.unwrapped_python_type}_{class_name}"
                cur = cur.parent

            self.deduplication_cache.add(class_name)
            return class_name


class AnonymousQueryError(Exception):
    def __init__(self):
        super().__init__("All queries must be named")


class InvalidQueryError(Exception):
    def __init__(self, errors):
        self.errors = errors
        message = "\n".join(str(err) for err in errors)
        super().__init__(message)


class QueryParser:
    def __init__(self, schema: GraphQLSchema):
        self.schema = schema

    def parse(self, query: str, should_validate: bool = True) -> ParsedNode:
        document_ast = parse(query)
        operation = get_operation_ast(document_ast)

        if not operation.name:
            raise AnonymousQueryError()

        if should_validate:
            errors = validate(self.schema, document_ast)
            if errors:
                raise InvalidQueryError(errors)

        type_info = TypeInfo(self.schema)
        visitor = FieldToTypeMatcherVisitor(self.schema, type_info, query)
        visit(document_ast, TypeInfoVisitor(type_info, visitor))
        return visitor.parsed
