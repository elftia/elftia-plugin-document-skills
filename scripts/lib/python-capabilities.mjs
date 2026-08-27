const STRING_PREFIXES = new Set(['b', 'br', 'f', 'fr', 'r', 'rb', 'rf', 'u']);
export const PUBLIC_OPERATION_PATTERN = /^[a-z0-9]+(?:[.-][a-z0-9]+)*$/;
export const PUBLIC_OPERATION_MAX_LENGTH = 128;
export const DOCUMENT_OPERATION_PREFIX = /^(?:docx|xlsx|pptx|pdf)\./;

export function isPublicOperation(operation) {
  return (
    operation.length <= PUBLIC_OPERATION_MAX_LENGTH && PUBLIC_OPERATION_PATTERN.test(operation)
  );
}

function lineAt(source, index) {
  return source.slice(0, index).split('\n').length;
}

function readString(source, start) {
  let quoteStart = start;
  if (/[a-z]/i.test(source[start])) {
    while (/[a-z]/i.test(source[quoteStart])) quoteStart += 1;
    const prefix = source.slice(start, quoteStart).toLowerCase();
    if (!STRING_PREFIXES.has(prefix) || !['"', "'"].includes(source[quoteStart])) return null;
  }
  const prefix = source.slice(start, quoteStart).toLowerCase();
  const quote = source[quoteStart];
  if (!['"', "'"].includes(quote)) return null;
  const triple = source.slice(quoteStart, quoteStart + 3) === quote.repeat(3);
  const delimiter = triple ? quote.repeat(3) : quote;
  const contentStart = quoteStart + delimiter.length;
  for (let index = contentStart; index < source.length; index += 1) {
    if (source[index] === '\\') {
      index += 1;
      continue;
    }
    if (source.slice(index, index + delimiter.length) !== delimiter) continue;
    const raw = source.slice(contentStart, index);
    const staticValue = /[bf]/.test(prefix) || raw.includes('\\') ? null : raw;
    return { end: index + delimiter.length, value: staticValue };
  }
  return { end: source.length, value: null };
}

function tokenize(source) {
  const tokens = [];
  for (let index = 0; index < source.length; ) {
    const character = source[index];
    if (/\s/.test(character)) {
      index += 1;
      continue;
    }
    if (character === '#') {
      const lineEnd = source.indexOf('\n', index + 1);
      index = lineEnd === -1 ? source.length : lineEnd + 1;
      continue;
    }
    const string = readString(source, index);
    if (string) {
      tokens.push({ index, type: 'string', value: string.value });
      index = string.end;
      continue;
    }
    if (/[A-Za-z_]/.test(character)) {
      let end = index + 1;
      while (/[A-Za-z0-9_]/.test(source[end])) end += 1;
      tokens.push({ index, type: 'identifier', value: source.slice(index, end) });
      index = end;
      continue;
    }
    tokens.push({ index, type: 'punctuation', value: character });
    index += 1;
  }
  return tokens;
}

function splitArguments(tokens, openIndex) {
  const argumentsList = [];
  const stack = ['('];
  let current = [];
  for (let index = openIndex + 1; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (['(', '[', '{'].includes(token.value)) stack.push(token.value);
    if ([')', ']', '}'].includes(token.value)) {
      if (token.value === ')' && stack.length === 1) {
        if (current.length > 0) argumentsList.push(current);
        return { argumentsList, endIndex: index };
      }
      stack.pop();
    }
    if (token.value === ',' && stack.length === 1) {
      if (current.length > 0) argumentsList.push(current);
      current = [];
    } else {
      current.push(token);
    }
  }
  return null;
}

function staticOperation(argumentsList) {
  let keyword = null;
  for (const argument of argumentsList) {
    if (argument[0]?.type === 'identifier' && argument[1]?.value === '=') {
      if (argument[0].value === 'operation') keyword = argument.slice(2);
      continue;
    }
    if (keyword == null) {
      keyword = argument;
      break;
    }
  }
  if (keyword?.length !== 1 || keyword[0].type !== 'string') return null;
  return keyword[0].value;
}

export function extractCapabilityOperations(source, relativePath) {
  const tokens = tokenize(source);
  const operations = new Set();
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token.type !== 'identifier' || token.value !== 'Capability') continue;
    if (tokens[index + 1]?.value !== '(') continue;
    const invocation = splitArguments(tokens, index + 1);
    const operation = invocation && staticOperation(invocation.argumentsList);
    if (!operation) {
      throw new Error(`${relativePath}:${lineAt(source, token.index)} has an unresolved Capability operation`);
    }
    if (!isPublicOperation(operation)) {
      throw new Error(`${relativePath}:${lineAt(source, token.index)} has an invalid Capability operation: ${operation}`);
    }
    if (DOCUMENT_OPERATION_PREFIX.test(operation)) operations.add(operation);
    index = invocation.endIndex;
  }
  return operations;
}
