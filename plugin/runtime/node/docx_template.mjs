/**
 * Original Elftia one-shot scalar DOCX renderer.
 *
 * Python owns request validation, token planning, archive security, preservation
 * validation, and promotion. This script renders only a bounded approved token set.
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import Docxtemplater from "docxtemplater";
import PizZip from "pizzip";

const MAX_INPUT_BYTES = 1024 * 1024;
const chunks = [];
let received = 0;

for await (const chunk of process.stdin) {
  received += chunk.length;
  if (received > MAX_INPUT_BYTES) {
    throw new Error("private input exceeds byte ceiling");
  }
  chunks.push(chunk);
}

const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const required = new Set([
  "protocol_version",
  "input",
  "output",
  "variables",
  "approved_tokens",
]);
if (
  request === null ||
  typeof request !== "object" ||
  Array.isArray(request) ||
  Object.keys(request).length !== required.size ||
  Object.keys(request).some((key) => !required.has(key)) ||
  request.protocol_version !== "1.0"
) {
  throw new Error("invalid private request envelope");
}

const input = path.normalize(request.input);
const output = path.normalize(request.output);
if (
  !path.isAbsolute(input) ||
  !path.isAbsolute(output) ||
  path.dirname(input) !== path.dirname(output) ||
  input === output ||
  path.basename(input) !== "template-input.docx" ||
  path.basename(output) !== "template-output.docx"
) {
  throw new Error("private template paths are not contained");
}
if (
  !Array.isArray(request.approved_tokens) ||
  request.approved_tokens.some(
    (token) =>
      typeof token !== "string" ||
      !/^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(token),
  ) ||
  new Set(request.approved_tokens).size !== request.approved_tokens.length
) {
  throw new Error("invalid approved token inventory");
}
const approved = new Set(request.approved_tokens);
const variableMap = new Map(Object.entries(request.variables));
if (
  request.variables === null ||
  typeof request.variables !== "object" ||
  Array.isArray(request.variables) ||
  Object.entries(request.variables).some(
    ([key, value]) =>
      !approved.has(key) ||
      typeof value !== "string" ||
      !Object.hasOwn(request.variables, key),
  )
) {
  throw new Error("invalid scalar variable binding");
}

const inputBytes = fs.readFileSync(input);
const zip = new PizZip(inputBytes);
const originalEntries = new Set(Object.keys(zip.files));
const originalContentTypes = zip.file("[Content_Types].xml").asNodeBuffer();
const document = new Docxtemplater(zip, {
  paragraphLoop: false,
  linebreaks: false,
  parser(tag) {
    if (!approved.has(tag)) {
      throw new Error("template tag differs from Python-approved inventory");
    }
    return {
      get() {
        return variableMap.get(tag);
      },
    };
  },
});
document.render(request.variables);
const renderedZip = document.getZip();
renderedZip.file("[Content_Types].xml", originalContentTypes);
for (const [entry, file] of Object.entries(renderedZip.files)) {
  if (file.dir && !originalEntries.has(entry)) {
    file.date = new Date(Date.UTC(1980, 0, 1, 0, 0, 0));
    continue;
  }
  file.date = new Date(Date.UTC(1980, 0, 1, 0, 0, 0));
  file.unixPermissions = 0o100644;
}
const rendered = renderedZip.generate({
  type: "nodebuffer",
  compression: "DEFLATE",
  compressionOptions: { level: 9 },
  platform: "UNIX",
});
fs.writeFileSync(output, rendered, { flag: "wx", mode: 0o600 });
process.stdout.write(
  JSON.stringify({
    protocol_version: "1.0",
    status: "success",
    backend: "docxtemplater",
    version: "3.69.3",
    approved_token_count: approved.size,
    bytes: rendered.length,
  }),
);
