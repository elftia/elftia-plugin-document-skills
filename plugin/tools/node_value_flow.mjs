export function bindPattern(
  pattern,
  value,
  bindings,
  relative,
  dangerousMembers,
  mcpMembers,
) {
  if (!pattern) return;
  requireSafe(value !== "dangerous", `dangerous Node binding flow:${relative}`);
  if (pattern.type === "Identifier") {
    bindings.set(pattern.name, value);
    return;
  }
  if (pattern.type === "AssignmentPattern") {
    bindPattern(
      pattern.left,
      value,
      bindings,
      relative,
      dangerousMembers,
      mcpMembers,
    );
    return;
  }
  if (pattern.type === "RestElement") {
    bindPattern(
      pattern.argument,
      value,
      bindings,
      relative,
      dangerousMembers,
      mcpMembers,
    );
    return;
  }
  if (pattern.type === "ArrayPattern") {
    for (const item of pattern.elements) {
      bindPattern(
        item,
        value,
        bindings,
        relative,
        dangerousMembers,
        mcpMembers,
      );
    }
    return;
  }
  if (pattern.type === "ObjectPattern") {
    for (const property of pattern.properties) {
      const name = property.type === "Property"
        ? propertyName(property, bindings)
        : null;
      requireSafe(
        name !== null &&
          !dangerousMembers.has(name) &&
          !mcpMembers.has(name),
        `dangerous or unknown Node destructuring:${name}:${relative}`,
      );
      bindPattern(
        property.type === "Property" ? property.value : property.argument,
        value,
        bindings,
        relative,
        dangerousMembers,
        mcpMembers,
      );
    }
  }
}

export function abstractValue(
  node,
  bindings,
  dangerousNames,
  globalNames,
) {
  if (!node) return "unknown";
  if (node.type === "ChainExpression") {
    return abstractValue(node.expression, bindings, dangerousNames, globalNames);
  }
  if (node.type === "Identifier") {
    if (
      dangerousNames.has(node.name) ||
      globalNames.has(node.name) ||
      node.name === "Reflect"
    ) {
      return "dangerous";
    }
    return bindings.get(node.name) || "unknown";
  }
  if (node.type === "Literal" && typeof node.value === "string") {
    return `string:${node.value}`;
  }
  if (node.type === "BinaryExpression" && node.operator === "+") {
    const left = abstractValue(node.left, bindings, dangerousNames, globalNames);
    const right = abstractValue(node.right, bindings, dangerousNames, globalNames);
    if (left.startsWith("string:") && right.startsWith("string:")) {
      return `string:${left.slice(7)}${right.slice(7)}`;
    }
  }
  if (node.type === "MemberExpression") {
    const base = abstractValue(
      node.object,
      bindings,
      dangerousNames,
      globalNames,
    );
    const property = memberName(node, bindings);
    if (
      base === "dangerous" ||
      property === null ||
      ["constructor", "createRequire", "eval", "Function", "require"].includes(
        property,
      )
    ) {
      return "dangerous";
    }
  }
  if (node.type === "ImportExpression") return "dangerous";
  if (
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression"
  ) {
    return "safe";
  }
  return "unknown";
}

export function memberName(node, bindings) {
  if (!node.computed && node.property.type === "Identifier") {
    return node.property.name;
  }
  return node.computed ? staticString(node.property, bindings) : null;
}

function propertyName(node, bindings) {
  if (!node.computed && node.key.type === "Identifier") return node.key.name;
  return staticString(node.key, bindings);
}

function staticString(node, bindings) {
  if (node?.type === "Literal" && typeof node.value === "string") {
    return node.value;
  }
  if (node?.type === "Identifier") {
    const value = bindings.get(node.name);
    return value?.startsWith("string:") ? value.slice(7) : null;
  }
  if (node?.type === "BinaryExpression" && node.operator === "+") {
    const left = staticString(node.left, bindings);
    const right = staticString(node.right, bindings);
    return left === null || right === null ? null : left + right;
  }
  return null;
}

function requireSafe(condition, message) {
  if (!condition) throw new Error(message);
}
