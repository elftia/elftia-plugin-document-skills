"""Bounded value-flow policy for distributable Python runtime code."""

import ast
from pathlib import PurePosixPath

from .python_policy_definitions import (
    DANGEROUS_ATTRIBUTES as _DANGEROUS_ATTRIBUTES,
    DANGEROUS_BUILTINS as _DANGEROUS_BUILTINS,
    MCP_PYTHON_PACKAGES,
    MCP_REGISTRATION as _MCP_REGISTRATION,
    definition_expressions,
    is_reflective_dunder as _is_reflective_dunder,
    literal_string as _literal_string,
    normalized as _normalized,
)
from .python_policy_flow import (
    AbstractValue,
    LiteralContainer,
    LiteralLookup,
    LocalFunction,
    ParameterValue,
    UNKNOWN,
    UNKNOWN_POLICY_SENSITIVE,
    is_policy_sensitive,
    lookup_value,
    mapping_value,
    sequence_value,
    subscript_value,
    unpack_values,
)
from .python_policy_functions import LocalFunctionSummaries
from .python_policy_imports import bind_imports, reject_static_mcp_imports
from .python_policy_values import (
    BUILTINS_NAMESPACE_VALUES,
    DICT_TYPE,
    attribute_value,
    is_policy_sensitive_default,
    rejects_builtin_lookup,
    string_value,
)


def audit_python_source(relative: str, text: str) -> None:
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as error:
        raise AssertionError(
            f"Python source cannot be structurally audited: {relative}"
        ) from error
    reject_static_mcp_imports(relative, tree)
    if is_runtime_python(relative):
        _PythonValueFlow(relative).audit(tree)


def is_runtime_python(relative: str) -> bool:
    parts = PurePosixPath(relative.replace("\\", "/")).parts
    return bool(parts) and parts[0] in {"src", "skills", "providers", "runtime"}


class _PythonValueFlow:
    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.scopes: list[dict[str, AbstractValue]] = [{}]
        self.functions = LocalFunctionSummaries()

    def audit(self, tree: ast.Module) -> None:
        self._statements(tree.body)

    def _statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.define(self, statement)
            elif isinstance(statement, ast.ClassDef):
                for expression in definition_expressions(statement):
                    self._expr(expression)
                self.scopes[-1][statement.name] = "safe"
                self.scopes.append({})
                self._statements(statement.body)
                self.scopes.pop()
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._import(statement)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                if isinstance(statement, ast.AnnAssign):
                    self._expr(statement.annotation)
                value = (
                    self._expr(statement.value)
                    if statement.value is not None
                    else "safe"
                )
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                for target in targets:
                    self._store(target, value)
            elif isinstance(statement, ast.Return):
                value = self._expr(statement.value) if statement.value else "safe"
                self.functions.capture_return(value)
            elif isinstance(statement, (ast.Expr, ast.Raise)):
                value = getattr(statement, "value", None) or getattr(
                    statement, "exc", None
                )
                if value is not None:
                    self._expr(value)
            else:
                for child in ast.iter_child_nodes(statement):
                    if isinstance(child, ast.expr):
                        self._expr(child)
                    elif isinstance(child, ast.stmt):
                        self._statements([child])

    def _import(self, statement: ast.Import | ast.ImportFrom) -> None:
        bind_imports(self, statement)

    def _expr(self, node: ast.expr) -> AbstractValue:
        literal = string_value(node)
        if literal is not None:
            return literal
        if isinstance(node, ast.Name):
            value = self._lookup(node.id)
            if value is None and (
                node.id in _DANGEROUS_BUILTINS or node.id == "__loader__"
            ):
                self._reject(f"Dangerous builtin identity referenced: {node.id}")
            if value is None and node.id == "__builtins__":
                return "namespace:builtins"
            if value is None and node.id == "dict":
                return DICT_TYPE
            return value or "unknown"
        if isinstance(node, ast.Attribute):
            base = self._expr(node.value)
            normalized = _normalized(node.attr)
            if (
                node.attr in _DANGEROUS_ATTRIBUTES
                or normalized in _MCP_REGISTRATION
                or base == "dangerous"
                or (
                    isinstance(base, str)
                    and base in {"module:builtins", "namespace:builtins"}
                    and (
                        node.attr in _DANGEROUS_BUILTINS
                        or _is_reflective_dunder(node.attr)
                    )
                )
            ):
                self._reject(f"Dangerous loader/reflection attribute: {node.attr}")
            if base == UNKNOWN_POLICY_SENSITIVE:
                self._reject("Unresolved policy-sensitive attribute is forbidden")
            if isinstance(base, LiteralContainer) and node.attr in {
                "__getitem__",
                "get",
            }:
                return LiteralLookup(base)
            lookup = attribute_value(base, node.attr) if isinstance(base, str) else None
            if lookup is not None:
                return lookup
            return (
                UNKNOWN
                if isinstance(base, str) and base.startswith("module:")
                else "safe"
            )
        if isinstance(node, ast.Subscript):
            base = self._expr(node.value)
            key = _literal_string(node.slice)
            self._expr(node.slice)
            if isinstance(base, LiteralContainer):
                return subscript_value(base, node.slice)
            if (
                isinstance(base, str)
                and (
                    base.startswith("module:")
                    or base == UNKNOWN_POLICY_SENSITIVE
                )
                or (
                    base in BUILTINS_NAMESPACE_VALUES
                    and (
                        key is None
                        or key in _DANGEROUS_BUILTINS
                        or key in _DANGEROUS_ATTRIBUTES
                        or _is_reflective_dunder(key)
                    )
                )
            ):
                self._reject("Module/reflection subscript identity is forbidden")
            return "safe"
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [self._expr(item) for item in node.elts]
            return sequence_value(type(node).__name__.casefold(), values)
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if key is not None:
                    self._expr(key)
            values = [self._expr(item) for item in node.values]
            return mapping_value(node.keys, values)
        if isinstance(node, ast.Await):
            return self._expr(node.value)
        if isinstance(node, ast.Call):
            target_value = self._expr(node.func)
            arguments = [
                *node.args,
                *(keyword.value for keyword in node.keywords),
            ]
            values = [self._expr(item) for item in arguments]
            if isinstance(target_value, str) and rejects_builtin_lookup(
                target_value, arguments, values
            ):
                self._reject("Builtin namespace loader/reflection lookup is forbidden")
            if target_value == UNKNOWN_POLICY_SENSITIVE:
                self._reject("Unresolved policy-sensitive callable is forbidden")
            if isinstance(target_value, LiteralLookup):
                default = values[1] if len(values) > 1 else "safe"
                return lookup_value(
                    target_value,
                    arguments[0] if arguments else None,
                    default,
                )
            if (
                target_value == DICT_TYPE
                or target_value == "callable:dict-lookup"
            ) and values and isinstance(values[0], LiteralContainer):
                default = values[2] if len(values) > 2 else "safe"
                return lookup_value(
                    LiteralLookup(values[0]),
                    arguments[1] if len(arguments) > 1 else None,
                    default,
                )
            if isinstance(target_value, LocalFunction):
                return self.functions.resolve_call(target_value, node, values)
            return (
                UNKNOWN_POLICY_SENSITIVE
                if any(is_policy_sensitive(item) for item in values)
                else UNKNOWN
            )
        if isinstance(node, ast.Lambda):
            return self.functions.lambda_value(self, node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self._expr(child)
        return "safe"

    def _argument_scope(
        self,
        arguments: ast.arguments,
        function_id: int | None = None,
    ) -> dict[str, AbstractValue]:
        positional = [*arguments.posonlyargs, *arguments.args]
        local = {
            argument.arg: (
                ParameterValue(function_id, argument.arg)
                if function_id is not None
                else "safe"
            )
            for argument in [*positional, *arguments.kwonlyargs]
        }
        if arguments.vararg:
            local[arguments.vararg.arg] = "safe"
        if arguments.kwarg:
            local[arguments.kwarg.arg] = "safe"
        defaults = zip(
            positional[-len(arguments.defaults) :],
            arguments.defaults,
        )
        keyword_defaults = zip(arguments.kwonlyargs, arguments.kw_defaults)
        for argument, default in [*defaults, *keyword_defaults]:
            if default is None:
                continue
            value = self._expr(default)
            if is_policy_sensitive_default(value):
                local[argument.arg] = value
        return local

    def _store(self, target: ast.expr, value: AbstractValue) -> None:
        if value == "dangerous":
            self._reject("Dangerous identity cannot be assigned or stored")
        if isinstance(target, ast.Name):
            self.scopes[-1][target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            unpacked = unpack_values(value, len(target.elts))
            for index, item in enumerate(target.elts):
                self._store(item, unpacked[index] if unpacked else value)
        else:
            self._expr(target)

    def _lookup(self, name: str) -> AbstractValue | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def _reject(self, detail: str) -> None:
        raise AssertionError(f"{detail} in runtime code: {self.relative}")

    @staticmethod
    def _require(condition: object, message: str) -> None:
        if not condition:
            raise AssertionError(message)
