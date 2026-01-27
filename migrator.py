#!/usr/bin/env python3
"""
Migrate classic agents -> new versioned agents, using PROJECT_ENDPOINT only.

Two-pass strategy:
  Pass 1: Create/Update all new agents WITHOUT connected_agent tools (to avoid dangling refs).
  Pass 2: For agents that had connected_agent tools, rewrite them to reference NEW agents using mapping,
          then Update the new agent definition.

- Reads classic agents via azure-ai-agents (AgentsClient)
- Checks existing new agents via REST API (list_versions endpoint) on PROJECT_ENDPOINT (NO hyena runtime)
- Creates/Updates new agents to mirror classic agent fields
- Skips creation if a new agent with the same name already exists (by versions check)
- NEVER deletes classic agents

Prereqs:
  pip install azure-ai-agents azure-identity python-dotenv requests

Env:
  PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<projectName>"
Optional:
  NEW_AGENTS_API_VERSION="v1"   # default v1
  DEBUG_HTTP="1"                # verbose request/response logs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple, Optional, Set

import requests
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

from azure.ai.agents import AgentsClient as ClassicAgentsClient

load_dotenv()

TOKEN_SCOPE = "https://ai.azure.com/.default"
NEW_AGENTS_API_VERSION = os.getenv("NEW_AGENTS_API_VERSION", "v1")
DEBUG_HTTP = os.getenv("DEBUG_HTTP", "").strip() not in ("", "0", "false", "False")


# ----------------------------
# Utils / Logging
# ----------------------------

def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", file=sys.stderr)


def log_json(level: str, obj: Any) -> None:
    txt = json.dumps(obj, indent=2, ensure_ascii=False)
    for line in txt.splitlines():
        log(level, line)


def _json_default(o: Any) -> Any:
    if hasattr(o, "as_dict"):
        return o.as_dict()
    if hasattr(o, "__dict__"):
        return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
    return str(o)


def to_dict(obj: Any) -> Dict[str, Any]:
    return json.loads(json.dumps(obj, default=_json_default))


def get_bearer_token(credential: DefaultAzureCredential) -> str:
    token = credential.get_token(TOKEN_SCOPE)
    return token.token


def _request(
    method: str,
    url: str,
    credential: DefaultAzureCredential,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> requests.Response:
    # Fail fast if anything tries to use hyena runtime endpoints
    if "hyena.infra.ai.azure.com" in url or "/agents/v2.0/" in url:
        raise RuntimeError(f"BUG: refusing to call hyena endpoint: {url}")

    token = get_bearer_token(credential)
    headers = {"Authorization": f"Bearer {token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    if DEBUG_HTTP:
        log("DEBUG", f"HTTP {method} {url}")
        if json_body is not None:
            log_json("DEBUG", {"request_body": json_body})

    resp = requests.request(
        method,
        url,
        headers=headers,
        json=json_body,
        timeout=timeout,
        allow_redirects=False,  # critical: don't silently jump to some other host
    )

    if DEBUG_HTTP:
        log("DEBUG", f"HTTP {resp.status_code} {method} {url}")
        ct = resp.headers.get("content-type", "")
        body_preview = resp.text[:1000] if ct else ""
        log("DEBUG", f"Response headers: {dict(resp.headers)}")
        if body_preview:
            log("DEBUG", f"Response body (first 1000 chars): {body_preview}")

    # Redirects are unexpected for project endpoint; make them loud
    if resp.status_code in (301, 302, 307, 308):
        loc = resp.headers.get("Location")
        raise RuntimeError(f"Unexpected redirect {resp.status_code} to {loc} for {url}")

    return resp


# ----------------------------
# Naming & Existence
# ----------------------------

def new_agent_name_from_classic(classic: dict) -> str:
    """
    Determine the target new agent name from a classic agent.
    - If metadata.v2_id exists, use that (strip the :version suffix)
    - Otherwise, slugify the classic name to match Foundry UI conventions
    """
    md = classic.get("metadata") or {}
    v2_id = md.get("v2_id")
    if isinstance(v2_id, str) and v2_id.strip():
        return v2_id.split(":")[0].strip()

    name = (classic.get("name") or "").strip()
    slug = name.lower()
    slug = re.sub(r"[\s_]+", "-", slug)          # spaces/underscores -> hyphen
    slug = re.sub(r"[^a-z0-9\-]", "", slug)      # drop weird chars
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or name


def new_agent_versions(project_endpoint: str, credential: DefaultAzureCredential, agent_name: str) -> List[Dict[str, Any]]:
    """
    GET {endpoint}/agents/{agentName}/versions?api-version=<NEW_AGENTS_API_VERSION>
    Returns [] if not found.
    """
    url = f"{project_endpoint.rstrip('/')}/agents/{agent_name}/versions?api-version={NEW_AGENTS_API_VERSION}"
    resp = _request("GET", url, credential, timeout=60)

    if resp.status_code == 404:
        return []
    if resp.status_code >= 400:
        raise RuntimeError(f"list_versions failed for {agent_name}: {resp.status_code} - {resp.text}")

    data = resp.json()
    versions = data.get("value") or data.get("data") or []
    if not isinstance(versions, list):
        return []
    return versions


def new_agent_exists(project_endpoint: str, credential: DefaultAzureCredential, agent_name: str) -> bool:
    # IMPORTANT: existence checks must be accurate; if they error, fail fast by default.
    # (You can change this behavior by adding --allow-unknown-existence)
    return len(new_agent_versions(project_endpoint, credential, agent_name)) > 0


# ----------------------------
# Create/Update new agent
# ----------------------------

def create_or_update_new_agent(
    project_endpoint: str,
    credential: DefaultAzureCredential,
    agent_name: str,
    definition: Dict[str, Any],
    metadata: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    POST {endpoint}/agents?api-version=<NEW_AGENTS_API_VERSION>

    NOTE:
      This sends a wrapper object with "name" and "definition" (and optional "metadata").
    """
    url = f"{project_endpoint.rstrip('/')}/agents?api-version={NEW_AGENTS_API_VERSION}"

    payload: Dict[str, Any] = {
        "name": agent_name,
        "definition": definition,
    }
    if metadata:
        payload["metadata"] = metadata

    resp = _request("POST", url, credential, json_body=payload, timeout=120)

    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to create/update agent {agent_name}: {resp.status_code} - {resp.text}")
    return resp.json()


def update_agent_version(
    project_endpoint: str,
    credential: DefaultAzureCredential,
    agent_name: str,
    definition: Dict[str, Any],
    metadata: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    POST {endpoint}/agents/{agentName}/versions?api-version=<NEW_AGENTS_API_VERSION>

    Creates a NEW VERSION of an existing agent (for PASS2 updates).
    """
    url = f"{project_endpoint.rstrip('/')}/agents/{agent_name}/versions?api-version={NEW_AGENTS_API_VERSION}"

    payload: Dict[str, Any] = {
        "definition": definition,
    }
    if metadata:
        payload["metadata"] = metadata

    resp = _request("POST", url, credential, json_body=payload, timeout=120)

    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to update agent version {agent_name}: {resp.status_code} - {resp.text}")
    return resp.json()



# ----------------------------
# Definition build / rewrite
# ----------------------------

def stringify_metadata(md: dict) -> dict:
    """
    Foundry requires metadata values to be strings.
    """
    out = {}
    for k, v in (md or {}).items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            out[k] = str(v)
        elif isinstance(v, (dict, list)):
            out[k] = json.dumps(v, ensure_ascii=False)
        else:
            out[k] = str(v)
    return out


def build_new_definition_from_classic(classic: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Best-effort copy of what exists on the classic agent object into new-agent definition.
    Returns (definition, metadata) tuple - metadata is top-level, not inside definition.
    """
    definition: Dict[str, Any] = {
        "kind": "prompt",
        "model": classic.get("model"),
        "instructions": classic.get("instructions") or "",
    }

    # Optional fields (keep them ONLY if service supports them; these usually work)
    for k in ["description", "temperature", "top_p", "response_format", "tools", "tool_resources"]:
        if classic.get(k) is not None:
            definition[k] = json.loads(json.dumps(classic[k], default=_json_default))

    # code_interpreter container hint
    tools = definition.get("tools") or []
    if isinstance(tools, list):
        for t in tools:
            if isinstance(t, dict) and t.get("type") == "code_interpreter":
                t.setdefault("container", {"type": "auto"})

    # file_search tool: copy vector_store_ids from tool_resources into the tool definition
    tool_resources = definition.get("tool_resources") or {}
    file_search_resources = tool_resources.get("file_search") or {}
    vector_store_ids = file_search_resources.get("vector_store_ids") or []
    if vector_store_ids and isinstance(tools, list):
        for t in tools:
            if isinstance(t, dict) and t.get("type") == "file_search":
                t["vector_store_ids"] = vector_store_ids

    # Metadata (top-level, not in definition) + provenance
    md = stringify_metadata(classic.get("metadata") or {})
    md["migrated_from_classic"] = "true"
    if classic.get("id"):
        md["migrated_from_classic_agent_id"] = str(classic["id"])
    if classic.get("name"):
        md["classic_name"] = str(classic["name"])

    return definition, md


def split_connected_agent_tools(definition: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Returns:
      - a copy of definition with connected_agent tools removed (pass1-safe)
      - list of removed connected_agent tools (for pass2)
    """
    d = json.loads(json.dumps(definition))
    tools = d.get("tools") or []
    if not isinstance(tools, list):
        return d, []

    connected = [t for t in tools if isinstance(t, dict) and t.get("type") == "connected_agent"]
    non_connected = [t for t in tools if not (isinstance(t, dict) and t.get("type") == "connected_agent")]

    if connected:
        d["tools"] = non_connected
    return d, connected


def rewrite_connected_agent_tool(
    classic_tool: Dict[str, Any],
    classic_to_new_by_id: Dict[str, str],
    classic_to_new_by_name: Dict[str, str],
) -> Dict[str, Any]:
    """
    Rewrite a classic connected_agent tool to reference the NEW agent.

    Classic shape (common):
      {"type":"connected_agent","connected_agent":{"name":"reference_agent","id":"asst_..."}}

    New shape can vary; this uses a conservative "agent_reference" shape:
      {"type":"connected_agent","agent":{"type":"agent_reference","name":"reference-agent"}}

    If your API expects a different schema, change ONLY here.
    """
    ca = (classic_tool.get("connected_agent") or {}) if isinstance(classic_tool, dict) else {}
    old_id = ca.get("id")
    old_name = ca.get("name")

    target_new: Optional[str] = None
    if old_id and old_id in classic_to_new_by_id:
        target_new = classic_to_new_by_id[old_id]
    elif old_name and old_name in classic_to_new_by_name:
        target_new = classic_to_new_by_name[old_name]

    if not target_new:
        raise RuntimeError(f"Cannot map connected_agent reference old_id={old_id!r} old_name={old_name!r}")

    return {
        "type": "connected_agent",
        "agent": {
            "type": "agent_reference",
            "name": target_new,
        },
        "_classic_connected_agent": ca,  # provenance for debugging
    }


def apply_connected_agent_rewrites(
    base_definition: Dict[str, Any],
    connected_tools: List[Dict[str, Any]],
    classic_to_new_by_id: Dict[str, str],
    classic_to_new_by_name: Dict[str, str],
) -> Dict[str, Any]:
    d = json.loads(json.dumps(base_definition))
    tools = d.get("tools") or []
    if not isinstance(tools, list):
        tools = []

    rewritten = [
        rewrite_connected_agent_tool(t, classic_to_new_by_id, classic_to_new_by_name)
        for t in connected_tools
    ]
    d["tools"] = tools + rewritten
    return d


# ----------------------------
# Main
# ----------------------------

def get_project_endpoint() -> str:
    ep = os.getenv("PROJECT_ENDPOINT") or os.getenv("PROJECT_ENDPOINT_STRING")
    if not ep:
        raise ValueError("Missing PROJECT_ENDPOINT (or PROJECT_ENDPOINT_STRING).")
    return ep


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate classic agents to new agents (2-pass, no deletes).")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created; don't create anything.")
    parser.add_argument(
        "--allow-unknown-existence",
        action="store_true",
        help="If existence checks error, treat as not-existing and proceed (can risk duplicates).",
    )
    args = parser.parse_args()

    endpoint = get_project_endpoint()
    credential = DefaultAzureCredential()
    classic_client = ClassicAgentsClient(endpoint=endpoint, credential=credential)

    classic_agents = list(classic_client.list_agents())
    log("INFO", f"Found classic agents: {len(classic_agents)}")

    # Pass 0: build mapping classic->new (by id and by name) + collect full classic definitions
    classic_to_new_by_id: Dict[str, str] = {}
    classic_to_new_by_name: Dict[str, str] = {}

    classic_fulls: List[Dict[str, Any]] = []
    for ca in classic_agents:
        ca_id = getattr(ca, "id", None) or to_dict(ca).get("id")
        if not ca_id:
            continue
        full = to_dict(classic_client.get_agent(ca_id))
        classic_fulls.append(full)

        cname = (full.get("name") or "").strip()
        nname = new_agent_name_from_classic(full)

        if full.get("id"):
            classic_to_new_by_id[full["id"]] = nname
        if cname:
            classic_to_new_by_name[cname] = nname

        log("DEBUG", f"map classic '{cname}' ({full.get('id')}) -> new '{nname}'")

    # Identify which classic agents have connected agents (for pass 2)
    connected_agent_classics: List[Dict[str, Any]] = []
    pass1_items: List[Dict[str, Any]] = []

    for full in classic_fulls:
        definition, metadata = build_new_definition_from_classic(full)
        pass1_def, connected_tools = split_connected_agent_tools(definition)

        item = {
            "classic_id": full.get("id"),
            "classic_name": full.get("name"),
            "target_new_name": new_agent_name_from_classic(full),
            "pass1_definition": pass1_def,
            "metadata": metadata,
            "connected_tools": connected_tools,
            "has_connected_agents": len(connected_tools) > 0,
        }
        pass1_items.append(item)
        if connected_tools:
            connected_agent_classics.append(item)

    log("INFO", f"Agents with connected_agent tools: {len(connected_agent_classics)}")
    if connected_agent_classics:
        log("INFO", "Connected-agent classics:")
        for it in connected_agent_classics:
            log("INFO", f"  - {it['classic_name']} -> {it['target_new_name']} (connected_tools={len(it['connected_tools'])})")

    results = {
        "project_endpoint": endpoint,
        "classic_count": len(classic_agents),
        "pass1": {"attempted": 0, "created_or_updated": [], "skipped_exists": [], "failed": []},
        "pass2": {"attempted": 0, "updated_connected": [], "skipped_missing_mapping": [], "failed": []},
        "connected_agent_classics": [
            {"classic_name": it["classic_name"], "classic_id": it["classic_id"], "target_new_name": it["target_new_name"]}
            for it in connected_agent_classics
        ],
        "dry_run": args.dry_run,
        "api_version": NEW_AGENTS_API_VERSION,
    }

    # Track which new agents will exist after pass1 (supports dry-run pass2)
    will_exist_after_pass1: Set[str] = set()

    # ----------------------------
    # Pass 1: create/update WITHOUT connected_agent tools
    # ----------------------------
    log("INFO", "PASS 1: creating/updating agents without connected_agent tools")
    for it in pass1_items:
        target = it["target_new_name"]
        cname = it["classic_name"]
        cid = it["classic_id"]
        pass1_def = it["pass1_definition"]
        metadata = it["metadata"]

        results["pass1"]["attempted"] += 1

        # existence check (strict by default)
        try:
            exists = new_agent_exists(endpoint, credential, target)
        except Exception as e:
            if args.allow_unknown_existence:
                log("WARN", f"Existence check error for {target}; proceeding as non-existent because --allow-unknown-existence. Error: {e}")
                exists = False
            else:
                results["pass1"]["failed"].append({
                    "classic_name": cname,
                    "classic_id": cid,
                    "target_new_name": target,
                    "error": f"Existence check failed (fail-fast): {e}",
                })
                log("ERROR", f"PASS1 abort item (existence check failed): {cname} -> {target}: {e}")
                continue

        if exists:
            will_exist_after_pass1.add(target)
            results["pass1"]["skipped_exists"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "reason": "new agent already exists (by versions check)",
            })
            log("INFO", f"PASS1 skip (exists): {cname} -> {target}")
            continue

        # Not exists -> will exist after pass1 if we create (or dry-run create)
        will_exist_after_pass1.add(target)

        if args.dry_run:
            results["pass1"]["created_or_updated"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "dry_run": True,
                "definition": pass1_def,
            })
            log("INFO", f"PASS1 dry-run create: {cname} -> {target}")
            continue

        try:
            created = create_or_update_new_agent(endpoint, credential, target, pass1_def, metadata=metadata)
            results["pass1"]["created_or_updated"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "new_agent": created,
            })
            log("INFO", f"PASS1 created/updated: {cname} -> {target}")
        except Exception as e:
            results["pass1"]["failed"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "error": str(e),
                "definition": pass1_def,
            })
            log("ERROR", f"PASS1 failed: {cname} -> {target}: {e}")

    # ----------------------------
    # Pass 2: update connected_agent wiring using mapping
    # ----------------------------
    log("INFO", "PASS 2: updating connected_agent wiring")
    for it in connected_agent_classics:
        target = it["target_new_name"]
        cname = it["classic_name"]
        cid = it["classic_id"]
        metadata = it["metadata"]

        results["pass2"]["attempted"] += 1

        # In dry-run, rely on will_exist_after_pass1
        base_exists = (target in will_exist_after_pass1) if args.dry_run else False

        if not args.dry_run:
            try:
                base_exists = new_agent_exists(endpoint, credential, target)
            except Exception as e:
                if args.allow_unknown_existence:
                    log("WARN", f"Existence check error for {target} in PASS2; proceeding as missing because --allow-unknown-existence. Error: {e}")
                    base_exists = False
                else:
                    results["pass2"]["failed"].append({
                        "classic_name": cname,
                        "classic_id": cid,
                        "target_new_name": target,
                        "error": f"Existence check failed (fail-fast): {e}",
                    })
                    log("ERROR", f"PASS2 abort item (existence check failed): {cname} -> {target}: {e}")
                    continue

        if not base_exists:
            results["pass2"]["failed"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "error": "Base new agent does not exist; cannot apply connected_agent wiring.",
            })
            log("ERROR", f"PASS2 cannot update wiring (missing new agent): {cname} -> {target}")
            continue

        base_def = it["pass1_definition"]
        connected_tools = it["connected_tools"]

        # Rewrite will fail-fast if any connected agent cannot be mapped
        try:
            updated_def = apply_connected_agent_rewrites(
                base_definition=base_def,
                connected_tools=connected_tools,
                classic_to_new_by_id=classic_to_new_by_id,
                classic_to_new_by_name=classic_to_new_by_name,
            )
        except Exception as e:
            results["pass2"]["skipped_missing_mapping"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "reason": "Some connected agents could not be mapped to new agents",
                "error": str(e),
            })
            log("WARN", f"PASS2 skip (missing mapping): {cname} -> {target}: {e}")
            continue

        if args.dry_run:
            results["pass2"]["updated_connected"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "dry_run": True,
                "updated_definition": updated_def,
            })
            log("INFO", f"PASS2 dry-run update wiring: {cname} -> {target}")
            continue

        try:
            # Use update_agent_version to create a new version (agent already exists)
            updated = update_agent_version(endpoint, credential, target, updated_def, metadata=metadata)
            results["pass2"]["updated_connected"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "new_agent": updated,
            })
            log("INFO", f"PASS2 updated wiring (new version): {cname} -> {target}")
        except Exception as e:
            results["pass2"]["failed"].append({
                "classic_name": cname,
                "classic_id": cid,
                "target_new_name": target,
                "error": str(e),
                "updated_definition": updated_def,
            })
            log("ERROR", f"PASS2 failed: {cname} -> {target}: {e}")

    # Final output (stdout)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
