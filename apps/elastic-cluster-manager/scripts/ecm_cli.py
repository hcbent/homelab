#!/usr/bin/env python3
"""Drive ECM's API from a terminal: plan a cluster, watch an operation, approve its plan. Standard library only.

    ecm_cli.py create NAME VERSION            a dry run: plans, creates nothing, the plan cannot be approved
    ecm_cli.py create NAME VERSION --real     a plan you can approve; approving it creates machines
    ecm_cli.py show OPERATION_ID [--logs N]   state, steps, plan, result and the last log lines
    ecm_cli.py watch OPERATION_ID             follow an operation until it finishes or needs approval
    ecm_cli.py approve OPERATION_ID DIGEST    approve the plan with that digest (shows the plan first)

Environment:
    ECM_URL             default https://ecm.lab.thewortmans.org
    ECM_ADMIN_USERNAME  default admin
    ECM_ADMIN_PASSWORD  the admin password; if unset you are asked for it, and what you type is not shown
    ECM_CA_FILE         a CA certificate to trust for ECM's HTTPS (verification stays on)

The password is never printed or put on a command line. ECM redacts its own log lines before they are stored.
"""
import argparse
import getpass
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

TERMINAL = {"succeeded", "failed", "cancelled"}
PAUSED = {"pending_approval"}


class CliError(Exception):
    """Something the user can act on. The message is printed as it is."""


class Client:
    def __init__(self, base_url: str, ca_file: str | None = None, insecure: bool = False):
        self.base = base_url.rstrip("/")
        context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        if insecure:
            context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=context))

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "X-ECM-CSRF": "1"})  # ECM refuses a state-changing request without it
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise CliError(f"{method} {path} -> {exc.code}: {self._detail(exc)}") from None
        except urllib.error.URLError as exc:
            raise CliError(f"could not reach {self.base}: {exc.reason}") from None
        return json.loads(raw) if raw else None

    @staticmethod
    def _detail(exc: urllib.error.HTTPError) -> str:
        try:
            detail = json.loads(exc.read()).get("detail", "")
            return detail if isinstance(detail, str) else json.dumps(detail)
        except (ValueError, AttributeError):
            return exc.reason or "request failed"

    def login(self, username: str, password: str) -> None:
        self.call("POST", "/api/auth/login", {"username": username, "password": password})


# ---- commands ------------------------------------------------------------------------------------------

def cmd_create(client: Client, args) -> int:
    body = {"name": args.name, "version": args.version, "preset": "three_node", "dry_run": not args.real}
    out = client.call("POST", "/api/clusters", body)
    kind = "DRY RUN (plans only, cannot be approved)" if out["dry_run"] else "REAL create (can be approved)"
    print(f"{kind}: cluster {args.name}, elasticsearch {args.version}")
    print(f"operation {out['operation_id']}   cluster {out['cluster_id']}")
    for node in out["nodes"]:
        print(f"  {node['name']:<14} host {node['host']:<6} address {node['address']:<16} vmid {node['vm_id']}")
    for warning in out.get("warnings") or []:
        print(f"  warning: {warning}")
    print(f"\nnext: {sys.argv[0]} watch {out['operation_id']}")
    return 0


def _print_plan(op: dict) -> None:
    plan = op.get("plan")
    if not plan:
        return
    summary = plan.get("summary") or {}
    print(f"plan digest: {plan['digest']}")
    print(f"  terraform: {summary.get('adds', 0)} to add, {summary.get('updates', 0)} to change, "
          f"{summary.get('deletes', 0)} to destroy")
    if summary.get("configure"):
        print(f"  then: {summary['configure']}")
    print(f"  approvable: {plan.get('approvable')}")


def cmd_show(client: Client, args) -> int:
    op = client.call("GET", f"/api/operations/{args.operation_id}")
    print(f"{op['kind']}  {op['state']}  phase={op['phase']}  {op['progress']['done']}/{op['progress']['total']} steps"
          f"  dry_run={op['dry_run']}")
    for step in op["steps"]:
        print(f"  {step['seq']}. {step['name']:<10} {step['status']}")
    if op.get("error"):
        print(f"error: {op['error']}")
    _print_plan(op)
    if op.get("result"):
        print(f"result: {json.dumps(op['result'])}")
    for line in op["logs"][-args.logs:] if args.logs else []:
        print(f"  [{line['stream']}] {line['line']}")
    return 1 if op["state"] == "failed" else 0


def cmd_watch(client: Client, args) -> int:
    deadline = time.monotonic() + args.timeout
    seen_logs, last = 0, None
    while True:
        op = client.call("GET", f"/api/operations/{args.operation_id}")
        status = (op["state"], op["phase"])
        if status != last:
            print(f"[{op['state']}] phase={op['phase']}  {op['progress']['done']}/{op['progress']['total']} steps")
            last = status
        for line in op["logs"][seen_logs:]:
            print(f"  [{line['stream']}] {line['line']}")
        seen_logs = len(op["logs"])
        if op["state"] in TERMINAL:
            if op["state"] == "failed":
                print(f"\nFAILED: {op['error']}")
                return 1
            if op.get("result"):
                print(f"result: {json.dumps(op['result'])}")
            return 0
        if op["state"] in PAUSED:
            print()
            _print_plan(op)
            if op["plan"] and op["plan"]["approvable"]:
                print(f"\nto approve:  {sys.argv[0]} approve {args.operation_id} {op['plan']['digest']}")
            return 0
        if time.monotonic() > deadline:
            print(f"\nstill {op['state']} after {args.timeout:g}s; run watch again to keep following")
            return 2
        time.sleep(args.interval)


def cmd_approve(client: Client, args) -> int:
    op = client.call("GET", f"/api/operations/{args.operation_id}")
    print(f"approving {op['kind']} {op['id']} ({op['state']})")
    _print_plan(op)
    client.call("POST", f"/api/operations/{args.operation_id}/approve", {"digest": args.digest})
    print("approved; ECM continues with the next phases.")
    print(f"next: {sys.argv[0]} watch {args.operation_id}")
    return 0


# ---- entry point ---------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Drive ECM's API from a terminal.")
    parser.add_argument("--insecure", action="store_true", help="do not verify ECM's HTTPS certificate")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="plan a three-node cluster (a dry run unless --real)")
    create.add_argument("name")
    create.add_argument("version")
    create.add_argument("--real", action="store_true", help="make a plan that can be approved")
    create.set_defaults(run=cmd_create)
    show = sub.add_parser("show", help="state, steps, plan and the last log lines")
    show.add_argument("operation_id")
    show.add_argument("--logs", type=int, default=15, help="how many log lines to show (default 15)")
    show.set_defaults(run=cmd_show)
    watch = sub.add_parser("watch", help="follow an operation until it finishes or needs approval")
    watch.add_argument("operation_id")
    watch.add_argument("--interval", type=float, default=5)
    watch.add_argument("--timeout", type=float, default=1800)
    watch.set_defaults(run=cmd_watch)
    approve = sub.add_parser("approve", help="approve the plan with this digest")
    approve.add_argument("operation_id")
    approve.add_argument("digest", help="the 64-character digest shown with the plan")
    approve.set_defaults(run=cmd_approve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = os.environ.get("ECM_URL", "https://ecm.lab.thewortmans.org")
    try:
        password = os.environ.get("ECM_ADMIN_PASSWORD") or getpass.getpass("ECM admin password: ")
        if not password:
            raise CliError("no password given")
        client = Client(base, os.environ.get("ECM_CA_FILE"), args.insecure)
        client.login(os.environ.get("ECM_ADMIN_USERNAME", "admin"), password)
        return args.run(client, args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
