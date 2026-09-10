"""Thin REST helpers for the Foundry data plane and Azure Resource Manager.

Used where there is no typed SDK path: the guardrail lives in Azure Resource
Manager, and skill publishing is a multipart upload. Toolbox and agent creation
use the azure-ai-projects SDK instead.
"""

import json
import mimetypes
from pathlib import Path

import requests
from azure.identity import DefaultAzureCredential

import config

_credential = DefaultAzureCredential()

# Data-plane preview features used by this sample.
FOUNDRY_FEATURES = "Skills=V1Preview, Toolboxes=V1Preview"


def token(scope: str) -> str:
    return _credential.get_token(scope).token


def _check(response: requests.Response, allow_404: bool = False):
    if allow_404 and response.status_code == 404:
        return None
    if not response.ok:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} -> "
            f"{response.status_code}\n{response.text}"
        )
    return response.json() if response.content else {}


def arm(method: str, resource_id: str, api_version: str, body: dict | None = None):
    """Call Azure Resource Manager for a control-plane resource such as an RAI policy."""
    url = f"{config.ARM_BASE}{resource_id}?api-version={api_version}"
    headers = {
        "Authorization": f"Bearer {token(config.ARM_SCOPE)}",
        "Content-Type": "application/json",
    }
    return _check(requests.request(method, url, headers=headers, json=body, timeout=120))


def upload_skill(skill_dir: Path) -> str:
    """Publish a skill folder as a new skill version.

    Every file under `skill_dir` is uploaded as a multipart part whose filename is
    the path relative to the folder, which is how the Skills API rebuilds the
    skill's directory layout on the service side.
    """
    name = skill_dir.name
    files = []
    for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(skill_dir).as_posix()
        ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        files.append(("files", (rel, path.read_bytes(), ctype)))

    url = (
        f"{config.PROJECT_ENDPOINT}/skills/{name}/versions"
        f"?api-version={config.API_VERSION}"
    )
    headers = {
        "Authorization": f"Bearer {token(config.FOUNDRY_SCOPE)}",
        "Accept": "application/json",
        "Foundry-Features": FOUNDRY_FEATURES,
    }
    result = _check(requests.post(url, headers=headers, files=files, timeout=300))
    print(f"  published skill '{name}' (version {result.get('version', '?')}, "
          f"{len(files)} file(s))")
    return name


def pretty(obj) -> str:
    return json.dumps(obj, indent=2, default=str)
