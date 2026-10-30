"""httpx MockTransport that serves recorded fixture files, so the REAL client code runs in tests.

It also enforces the read-only guarantee: any non-GET request fails the test.
"""
import json
from pathlib import Path

import httpx

DATA = Path(__file__).parent / "data"
PVE_TOKEN = "PVEAPIToken=ro@pve!ecm=fixture-pve-secret-value"
ES_KEY = "ApiKey Zml4dHVyZS1hcGkta2V5"


class FixtureTransport(httpx.MockTransport):
    def __init__(self):
        self.requests: list[httpx.Request] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET", f"discovery must be read-only, got {request.method}"
        host, path = request.url.host, request.url.path.strip("/")
        auth = request.headers.get("authorization")
        if path.startswith("api2/json"):
            if auth != PVE_TOKEN:
                return httpx.Response(401, json={"errors": "no ticket"})
            rel = "proxmox/" + path[len("api2/json/"):]
        else:
            if auth != ES_KEY:
                return httpx.Response(401, json={"error": "security_exception"})
            rel = f"elasticsearch/{host}/" + (path or "root")
        f = DATA / (rel + ".json")
        if not f.exists():
            # Proxmox answers 500 when the guest agent is not running
            return httpx.Response(500 if "agent" in rel else 404, json={"errors": "not found"})
        return httpx.Response(200, content=json.dumps(json.loads(f.read_text())))

    @property
    def methods(self) -> set[str]:
        return {r.method for r in self.requests}
