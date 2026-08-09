"""Bounded local-function return summaries for the Python runtime policy."""

from __future__ import annotations

import ast
from typing import Protocol

from .python_policy_definitions import definition_expressions
from .python_policy_flow import (
    AbstractValue,
    FunctionSummary,
    LocalFunction,
    UNKNOWN,
    resolve_summary,
    summarize_returns,
)


class _FlowHost(Protocol):
    scopes: list[dict[str, AbstractValue]]

    def _expr(self, node: ast.expr) -> AbstractValue: ...

    def _statements(self, statements: list[ast.stmt]) -> None: ...

    def _argument_scope(
        self,
        arguments: ast.arguments,
        function_id: int | None = None,
    ) -> dict[str, AbstractValue]: ...


class LocalFunctionSummaries:
    def __init__(self) -> None:
        self.summaries: dict[int, FunctionSummary] = {}
        self.return_values: list[list[AbstractValue]] = []
        self._next_function_id = 1

    def define(
        self,
        host: _FlowHost,
        statement: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for expression in definition_expressions(statement):
            host._expr(expression)
        function_id = self._new_id()
        host.scopes[-1][statement.name] = LocalFunction(function_id)
        defaults = self._default_bindings(host, statement.args)
        parameters = self._parameter_names(statement.args)
        self.summaries[function_id] = FunctionSummary(
            parameters, tuple(defaults.items()), UNKNOWN
        )
        self.return_values.append([])
        host.scopes.append(host._argument_scope(statement.args, function_id))
        host._statements(statement.body)
        host.scopes.pop()
        returned = summarize_returns(self.return_values.pop())
        self.summaries[function_id] = FunctionSummary(
            parameters, tuple(defaults.items()), returned
        )

    def lambda_value(self, host: _FlowHost, node: ast.Lambda) -> LocalFunction:
        for expression in definition_expressions(node):
            host._expr(expression)
        function_id = self._new_id()
        defaults = self._default_bindings(host, node.args)
        parameters = self._parameter_names(node.args)
        host.scopes.append(host._argument_scope(node.args, function_id))
        returned = host._expr(node.body)
        host.scopes.pop()
        self.summaries[function_id] = FunctionSummary(
            parameters, tuple(defaults.items()), returned
        )
        return LocalFunction(function_id)

    def capture_return(self, value: AbstractValue) -> None:
        if self.return_values:
            self.return_values[-1].append(value)

    def resolve_call(
        self,
        target: LocalFunction,
        node: ast.Call,
        values: list[AbstractValue],
    ) -> AbstractValue:
        summary = self.summaries.get(target.function_id)
        if summary is None:
            return UNKNOWN
        keyword_values = values[len(node.args) :]
        keywords = {
            keyword.arg: value
            for keyword, value in zip(node.keywords, keyword_values)
            if keyword.arg is not None
        }
        return resolve_summary(
            summary,
            target.function_id,
            values[: len(node.args)],
            keywords,
        )

    @staticmethod
    def _default_bindings(
        host: _FlowHost,
        arguments: ast.arguments,
    ) -> dict[str, AbstractValue]:
        positional = [*arguments.posonlyargs, *arguments.args]
        pairs = [
            *zip(positional[-len(arguments.defaults) :], arguments.defaults),
            *zip(arguments.kwonlyargs, arguments.kw_defaults),
        ]
        return {
            argument.arg: host._expr(default)
            for argument, default in pairs
            if default is not None
        }

    @staticmethod
    def _parameter_names(arguments: ast.arguments) -> tuple[str, ...]:
        return tuple(
            argument.arg
            for argument in [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ]
        )

    def _new_id(self) -> int:
        current = self._next_function_id
        self._next_function_id += 1
        return current
