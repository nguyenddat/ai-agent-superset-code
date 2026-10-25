"""Smoke-test the deployed Semantic Layer API through the running Superset.

Usage: uv run scripts/smoke.py

Logs in through the Superset login form as the admin (SUPERSET_ADMIN_USERNAME / SUPERSET_ADMIN_PASSWORD, default
admin/admin), then calls
the read-only Semantic Layer endpoints and checks that each answers 200 with a JSON object. Run it
after scripts/deploy.py; it does not change any data.
"""

import argparse
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from _common import API_PREFIX, SUPERSET_URL, fail, step, wait_for_health

SEMANTIC_API = f"{API_PREFIX}/semantic-layer"
EXPERT_RULES_API = f"{API_PREFIX}/expert-rules"

READ_ONLY_ENDPOINTS = [
    f"{SEMANTIC_API}/access",
    f"{SEMANTIC_API}/semantic-catalog",
    f"{SEMANTIC_API}/datasets/reference-options",
    f"{SEMANTIC_API}/data-layers",
    f"{SEMANTIC_API}/glossary",
    f"{SEMANTIC_API}/glossary/options",
    f"{SEMANTIC_API}/glossary/discovery",
    f"{EXPERT_RULES_API}/expert-rules/discover",
]


def _request(opener: urllib.request.OpenerDirector, path: str, form: dict | None = None) -> tuple[int, object]:
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(f"{SUPERSET_URL}{path}", data=data, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=60) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def _login() -> urllib.request.OpenerDirector:
    """Log in through the /login/ form, because the extension reads the admin role from the browser session."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    status, page = _request(opener, "/login/")
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page if isinstance(page, str) else "")
    if status != 200 or not match:
        fail(f"could not read the CSRF token from /login/ ({status})")
    _request(
        opener,
        "/login/",
        form={
            "csrf_token": match.group(1),
            "username": os.getenv("SUPERSET_ADMIN_USERNAME", "admin"),
            "password": os.getenv("SUPERSET_ADMIN_PASSWORD", "admin"),
        },
    )
    status, me = _request(opener, "/api/v1/me/")
    if status != 200:
        fail(f"admin login failed: /api/v1/me/ answered {status}")
    print(f"Logged in as {me['result']['username']}.")
    return opener


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)

    step(f"Logging in to {SUPERSET_URL}")
    wait_for_health(timeout=30)
    opener = _login()

    endpoints = list(READ_ONLY_ENDPOINTS)
    status, datasets = _request(opener, "/api/v1/dataset/?q=(page_size:1)")
    if status == 200 and isinstance(datasets, dict) and datasets.get("result"):
        dataset = datasets["result"][0]
        endpoints.append(f"{SEMANTIC_API}/dataset/{dataset['id']}/dictionary")
        endpoints.append(f"{SEMANTIC_API}/business-model?database_id={dataset['database']['id']}")
        endpoints.append(f"{SEMANTIC_API}/metric-contracts?database_id={dataset['database']['id']}")
    else:
        print("No Superset dataset found; skipping the dataset dictionary, business model and metric endpoints.")

    step("Calling the Semantic Layer API")
    failures = []
    for path in endpoints:
        status, payload = _request(opener, path)
        ok = status == 200 and isinstance(payload, dict)
        print(f"{'ok  ' if ok else 'FAIL'} {status} GET {path}")
        if not ok:
            failures.append(path)
            print(f"     {str(payload)[:300]}")

    step("Summary")
    if failures:
        fail(f"{len(failures)} of {len(endpoints)} endpoints failed")
    print(f"All {len(endpoints)} endpoints answered 200.")


if __name__ == "__main__":
    main()
