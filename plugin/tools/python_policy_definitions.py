"""Constants and AST surface helpers for the Python runtime policy."""

import ast

MCP_PYTHON_PACKAGES = {"fastmcp", "mcp", "modelcontextprotocol"}
DANGEROUS_BUILTINS = {
    "__import__",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "locals",
    "setattr",
    "vars",
}
DANGEROUS_MODULES = {"imp", "importlib", "operator", "pkgutil", "runpy"}
DANGEROUS_ATTRIBUTES = {
    "__bases__",
    "__class__",
    "__dict__",
    "__getattribute__",
    "__loader__",
    "__mro__",
    "__subclasses__",
    "attrgetter",
    "create_module",
    "exec_module",
    "find_spec",
    "import_module",
    "load_module",
    "methodcaller",
    "module_from_spec",
    "spec_from_file_location",
}
MCP_REGISTRATION = {
    "fastmcp",
    "mcpserver",
    "prompt",
    "registerprompt",
    "registerresource",
    "registertool",
    "resource",
    "setrequesthandler",
    "sseservertransport",
    "stdioservertransport",
    "tool",
}
ALLOWED_STDLIB = {
    "__future__",
    "argparse",
    "builtins",
    "collections",
    "contextlib",
    "copy",
    "csv",
    "ctypes",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "hashlib",
    "io",
    "json",
    "math",
    "os",
    "pathlib",
    "posixpath",
    "re",
    "secrets",
    "shutil",
    "signal",
    "stat",
    "struct",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "typing",
    "unicodedata",
    "uuid",
    "xml",
    "zipfile",
    "zlib",
}


def definition_expressions(
    statement: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda,
) -> list[ast.expr]:
    if isinstance(statement, ast.ClassDef):
        return [
            *statement.decorator_list,
            *statement.bases,
            *(keyword.value for keyword in statement.keywords),
        ]
    if isinstance(statement, ast.Lambda):
        return [
            *statement.args.defaults,
            *(item for item in statement.args.kw_defaults if item is not None),
        ]
    arguments = [
        *statement.args.posonlyargs,
        *statement.args.args,
        *statement.args.kwonlyargs,
    ]
    if statement.args.vararg:
        arguments.append(statement.args.vararg)
    if statement.args.kwarg:
        arguments.append(statement.args.kwarg)
    expressions = [
        *statement.decorator_list,
        *statement.args.defaults,
        *(item for item in statement.args.kw_defaults if item is not None),
        *(argument.annotation for argument in arguments if argument.annotation),
    ]
    if statement.returns:
        expressions.append(statement.returns)
    return expressions


def literal_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = literal_string(node.left)
        right = literal_string(node.right)
        return None if left is None or right is None else left + right
    return None


def normalized(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def is_reflective_dunder(value: str) -> bool:
    return value.startswith("__") and value.endswith("__") and value not in {
        "__file__",
        "__name__",
        "__package__",
    }
