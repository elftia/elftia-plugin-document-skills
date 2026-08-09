import json
import subprocess
import sys
import time

mode = sys.argv[1]
if mode == "hang":
    time.sleep(10)
elif mode == "crash":
    raise SystemExit(7)
elif mode == "invalid":
    print("not json")
elif mode == "secret":
    print("api_key=topsecret", file=sys.stderr)
    print('{"protocol_version":"1.0","ok":true}')
elif mode == "overflow_stdout":
    sys.stdout.buffer.write(b"x" * (4 * 1024 * 1024))
elif mode == "overflow_stderr":
    sys.stderr.buffer.write(b"x" * (4 * 1024 * 1024))
elif mode == "descendant_handles":
    subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        shell=False,
    )
    print('{"protocol_version":"1.0","ok":true}')
else:
    request = json.load(sys.stdin)
    print(json.dumps({"protocol_version": "1.0", "ok": request.get("ok") is True}))
