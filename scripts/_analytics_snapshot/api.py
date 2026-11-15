"""Orbit CLI and local dashboard access for analytics snapshots."""

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request


def orbit_json(args, workspace=None, timeout=600):
    cmd = ["orbit"]
    if workspace:
        cmd.extend(["--workspace", workspace])
    cmd.extend([*args, "--json"])
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else exc.returncode
        raise SystemExit(f"orbit {' '.join(args)} failed ({tail})") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"orbit {' '.join(args)} timed out") from exc
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"orbit {' '.join(args)} did not return JSON") from exc


def orbit_version():
    proc = subprocess.run(["orbit", "--version"], check=True, capture_output=True, text=True, timeout=30)
    parts = proc.stdout.strip().split()
    return parts[-1] if parts else proc.stdout.strip()


def scorecard_supports_until():
    proc = subprocess.run(
        ["orbit", "agents", "scorecard", "--help"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return "--until" in proc.stdout


def workspace_id(name):
    listed = orbit_json(["workspace", "list"])
    if not isinstance(listed, list):
        raise SystemExit("orbit workspace list did not return a list")
    for entry in listed:
        if isinstance(entry, dict) and entry.get("name") == name and entry.get("status") == "active":
            ident = entry.get("id")
            if isinstance(ident, str) and ident:
                return ident
    raise SystemExit(f"no active workspace named {name}")


def check_dashboard(url):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "http" or host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("dashboard URL must be loopback http (127.0.0.1, localhost or ::1)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SystemExit("dashboard URL must be a bare loopback origin")
    return url.rstrip("/")


def http_json(base, path, query):
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"dashboard {path} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"dashboard {path} was unreachable ({exc.reason})") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"dashboard {path} did not return JSON") from exc
