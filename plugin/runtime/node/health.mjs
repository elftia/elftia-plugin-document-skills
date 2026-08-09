const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);

let request;
try {
  request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
} catch {
  process.stdout.write(JSON.stringify({ protocol_version: "1.0", ok: false, error: "invalid_json" }));
  process.exitCode = 2;
}

if (request) {
  const result = {
    protocol_version: "1.0",
    ok: request.protocol_version === "1.0" && request.operation === "health",
    provider: "core-node",
    node_version: process.version,
  };
  process.stdout.write(JSON.stringify(result));
}

