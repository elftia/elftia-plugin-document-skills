import { parse } from "acorn";

import { abstractValue, bindPattern, memberName } from "./node_value_flow.mjs";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);

let request;
try {
  request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
} catch {
  process.stdout.write(JSON.stringify({ ok: false, error: "invalid_request" }));
  process.exitCode = 2;
}

if (request) {
  try {
    const tree = parse(request.source, {
      ecmaVersion: "latest",
      sourceType: "module",
      allowHashBang: true,
    });
    audit(tree, request.relative);
    process.stdout.write(JSON.stringify({ ok: true }));
  } catch (error) {
    process.stdout.write(
      JSON.stringify({
        ok: false,
        error: error instanceof SyntaxError ? "syntax" : "policy",
        category: String(error?.message || "node_policy_failure").slice(0, 256),
      }),
    );
    process.exitCode = 2;
  }
}

function audit(tree, relative) {
  const bindings = new Map();
  const dangerousNames = new Set([
    "require",
    "createRequire",
    "eval",
    "Function",
  ]);
  const globalNames = new Set(["globalThis", "global", "self", "window"]);
  const dangerousModules = new Set([
    "node:child_process",
    "child_process",
    "node:module",
    "module",
    "node:vm",
    "vm",
    "node:worker_threads",
    "worker_threads",
  ]);
  const dangerousMembers = new Set([
    "createRequire",
    "constructor",
    "eval",
    "Function",
    "require",
    "resolve",
    "runInContext",
    "runInNewContext",
    "runInThisContext",
    "Worker",
  ]);
  const mcpMembers = new Set([
    "FastMCP",
    "McpServer",
    "registerTool",
    "setRequestHandler",
    "SSEServerTransport",
    "StdioServerTransport",
    "tool",
    "resource",
    "prompt",
  ]);
  walk(tree, null, (node, parent) => {
    if (node.type === "FunctionDeclaration" && node.id) {
      bindings.set(node.id.name, "safe");
    }
    if (node.type === "VariableDeclarator") {
      bindPattern(
        node.id,
        abstractValue(node.init, bindings, dangerousNames, globalNames),
        bindings,
        relative,
        dangerousMembers,
        mcpMembers,
      );
    }
    if (node.type === "AssignmentExpression") {
      bindPattern(
        node.left,
        abstractValue(node.right, bindings, dangerousNames, globalNames),
        bindings,
        relative,
        dangerousMembers,
        mcpMembers,
      );
    }
    if (node.type === "ImportDeclaration") {
      denySpecifier(node.source.value, relative, dangerousModules);
      for (const specifier of node.specifiers) {
        const imported = specifier.imported?.name || specifier.local?.name;
        requireSafe(
          !dangerousNames.has(imported) && !dangerousMembers.has(imported),
          `dangerous Node import identity:${imported}:${relative}`,
        );
        bindings.set(specifier.local.name, "safe");
      }
    }
    if (node.type === "ImportExpression") {
      throw new Error(`dynamic import is forbidden:${relative}`);
    }
    if (
      node.type === "Identifier" &&
      (dangerousNames.has(node.name) ||
        globalNames.has(node.name) ||
        node.name === "Reflect" ||
        bindings.get(node.name) === "dangerous") &&
      isReference(node, parent)
    ) {
      throw new Error(`dangerous Node identity:${node.name}:${relative}`);
    }
    if (node.type === "MemberExpression") {
      const property = memberName(node, bindings);
      requireSafe(
        !dangerousMembers.has(property) && !mcpMembers.has(property),
        `dangerous Node member:${property}:${relative}`,
      );
      if (node.computed && property === null) {
        throw new Error(`computed Node member is not statically known:${relative}`);
      }
    }
    if (node.type === "CallExpression" || node.type === "NewExpression") {
      requireSafe(
        abstractValue(
          node.callee,
          bindings,
          dangerousNames,
          globalNames,
        ) !== "dangerous",
        `dangerous Node callable flow:${relative}`,
      );
    }
    if (node.type === "ReturnStatement" && node.argument) {
      requireSafe(
        abstractValue(
          node.argument,
          bindings,
          dangerousNames,
          globalNames,
        ) !== "dangerous",
        `dangerous Node return flow:${relative}`,
      );
    }
    if (node.type === "MetaProperty" && node.meta.name === "import") {
      throw new Error(`import.meta is forbidden in provider runtime:${relative}`);
    }
    if (node.type === "Literal" && typeof node.value === "string") {
      denySpecifier(node.value, relative, dangerousModules);
    }
    if (
      (node.type === "CallExpression" || node.type === "NewExpression") &&
      node.callee?.type === "MemberExpression" &&
      node.callee.computed &&
      memberName(node.callee, bindings) === null
    ) {
      throw new Error(`unknown computed call identity:${relative}`);
    }
  });
}

function denySpecifier(value, relative, dangerousModules) {
  const normalized = String(value).toLowerCase();
  requireSafe(
    !dangerousModules.has(normalized) &&
      !normalized.includes("@modelcontextprotocol") &&
      !normalized.includes("fastmcp") &&
      !/(^|[/_-])mcp([/_.-]|$)/.test(normalized),
    `forbidden Node module/specifier:${relative}`,
  );
}

function isReference(node, parent) {
  if (!parent) return true;
  if (
    (parent.type === "Property" && parent.key === node && !parent.computed) ||
    (parent.type === "MemberExpression" && parent.property === node && !parent.computed)
  ) {
    return false;
  }
  return true;
}

function walk(node, parent, callback) {
  if (!node || typeof node !== "object") return;
  callback(node, parent);
  for (const [key, value] of Object.entries(node)) {
    if (key === "start" || key === "end") continue;
    if (Array.isArray(value)) {
      for (const child of value) walk(child, node, callback);
    } else if (value && typeof value.type === "string") {
      walk(value, node, callback);
    }
  }
}

function requireSafe(condition, message) {
  if (!condition) throw new Error(message);
}
