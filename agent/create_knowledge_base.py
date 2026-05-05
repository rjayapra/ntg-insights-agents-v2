#!/usr/bin/env python3
"""
Create (or update) a Foundry IQ knowledge base end-to-end:

  1. Create a SearchIndexKnowledgeSource on Azure AI Search that wraps an
     existing search index. (The KS is a Foundry IQ wrapper object; the
     underlying search index must already exist and be populated.)
  2. Create / update the KnowledgeBase on Azure AI Search, wired to a
     supported Azure OpenAI LLM for query planning + answer synthesis.
  3. Create / update a `RemoteTool` connection on the Foundry project that
     points to the KB MCP endpoint, so agents can attach it as an MCPTool.

Idempotent: each step does create-or-update.

All inputs are env-driven; CLI flags can override individual values.

Required env (place in .env):

    PROJECT_RESOURCE_ID        ARM id of the Foundry project
    SEARCH_ENDPOINT            https://<search>.search.windows.net
    SEARCH_INDEX_NAME          existing search index to wrap
    AOAI_ENDPOINT              https://<account>.cognitiveservices.azure.com/
    AOAI_CHAT_DEPLOYMENT       e.g. gpt-4.1
    AOAI_CHAT_MODEL            e.g. gpt-4.1

Optional env (sensible defaults):

    SEARCH_ADMIN_KEY           AI Search admin key. If set, the script uses key
                               auth for the Search data plane (KS/KB CRUD)
                               instead of DefaultAzureCredential. The Foundry
                               project connection step still uses AAD.


    KB_NAME                    default: ntg-shared-kb
    KS_NAME                    default: ntg-shared-ks
    KB_CONNECTION_NAME         default: ntg-shared-kb-mcp
    KB_DESCRIPTION             default: "Shared NTG knowledge base"
    KB_RETRIEVAL_INSTRUCTIONS  optional retrieval/source-selection prompt
    KB_ANSWER_INSTRUCTIONS     default: "Return the top search result and include citations to source documents."
    KB_REASONING_EFFORT        minimal | low | medium  (default: low; medium is not supported in all regions, e.g. Canada East)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

import requests
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    KnowledgeBase,
    KnowledgeBaseAzureOpenAIModel,
    KnowledgeSourceReference,
    AzureOpenAIVectorizerParameters,
    SearchIndexKnowledgeSource,
    SearchIndexKnowledgeSourceParameters,
    KnowledgeRetrievalMinimalReasoningEffort,
    KnowledgeRetrievalLowReasoningEffort,
    KnowledgeRetrievalMediumReasoningEffort,
)

load_dotenv()

KB_API_VERSION = "2025-11-01-preview"
ARM_CONNECTION_API_VERSION = "2025-10-01-preview"

DEFAULT_KB_NAME = "ntg-shared-kb"
DEFAULT_KS_NAME = "ntg-shared-ks"
DEFAULT_CONNECTION_NAME = "ntg-shared-kb-mcp"
DEFAULT_DESCRIPTION = "Shared NTG knowledge base"
DEFAULT_ANSWER_INSTRUCTIONS = (
    "Return the top search result and include citations to source documents."
)
DEFAULT_REASONING_EFFORT = "low"


def log(msg: str) -> None:
    print(f"[kb] {msg}", file=sys.stderr)


def required_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        sys.exit(f"ERROR: required env var {name} not set")
    return val


def build_reasoning_effort(value: str):
    v = (value or "").strip().lower()
    if v == "minimal":
        return KnowledgeRetrievalMinimalReasoningEffort()
    if v == "low":
        return KnowledgeRetrievalLowReasoningEffort()
    if v in ("", "medium"):
        return KnowledgeRetrievalMediumReasoningEffort()
    sys.exit(f"ERROR: unknown KB_REASONING_EFFORT '{value}' (use minimal|low|medium)")


# ----------------------------------------------------------------------
# Step 1: Search Index Knowledge Source (idempotent)
# ----------------------------------------------------------------------
def ensure_knowledge_source(
    index_client: SearchIndexClient,
    ks_name: str,
    search_index_name: str,
    description: str,
) -> None:
    try:
        index_client.get_knowledge_source(ks_name)
        log(f"Knowledge source '{ks_name}' already exists; updating.")
    except ResourceNotFoundError:
        log(f"Knowledge source '{ks_name}' not found; creating.")

    ks = SearchIndexKnowledgeSource(
        name=ks_name,
        description=description,
        search_index_parameters=SearchIndexKnowledgeSourceParameters(
            search_index_name=search_index_name,
        ),
    )
    index_client.create_or_update_knowledge_source(ks)
    log(f"Knowledge source '{ks_name}' -> index '{search_index_name}' ready.")


# ----------------------------------------------------------------------
# Step 2: Knowledge Base (idempotent)
# ----------------------------------------------------------------------
def ensure_knowledge_base(
    index_client: SearchIndexClient,
    kb_name: str,
    ks_name: str,
    description: str,
    retrieval_instructions: Optional[str],
    answer_instructions: Optional[str],
    reasoning_effort_value: str,
    aoai_endpoint: str,
    aoai_deployment: str,
    aoai_model: str,
) -> None:
    try:
        index_client.get_knowledge_base(kb_name)
        log(f"Knowledge base '{kb_name}' already exists; updating.")
    except ResourceNotFoundError:
        log(f"Knowledge base '{kb_name}' not found; creating.")

    aoai_params = AzureOpenAIVectorizerParameters(
        resource_url=aoai_endpoint,
        deployment_name=aoai_deployment,
        model_name=aoai_model,
        # No api_key -> SDK uses the search service's managed identity / RBAC.
    )

    kb = KnowledgeBase(
        name=kb_name,
        description=description,
        retrieval_instructions=retrieval_instructions or None,
        answer_instructions=answer_instructions or None,
        knowledge_sources=[KnowledgeSourceReference(name=ks_name)],
        models=[KnowledgeBaseAzureOpenAIModel(azure_open_ai_parameters=aoai_params)],
        retrieval_reasoning_effort=build_reasoning_effort(reasoning_effort_value),
    )
    index_client.create_or_update_knowledge_base(kb)
    log(f"Knowledge base '{kb_name}' ready (reasoning_effort={reasoning_effort_value}).")


# ----------------------------------------------------------------------
# Step 3: Foundry project RemoteTool connection (idempotent)
# ----------------------------------------------------------------------
def ensure_project_connection(
    credential: DefaultAzureCredential,
    project_resource_id: str,
    connection_name: str,
    search_endpoint: str,
    kb_name: str,
) -> str:
    """Create / update a RemoteTool connection on the Foundry project that
    targets the KB MCP endpoint, using the project's managed identity."""
    mcp_endpoint = (
        f"{search_endpoint.rstrip('/')}/knowledgebases/{kb_name}"
        f"/mcp?api-version={KB_API_VERSION}"
    )

    token_provider = get_bearer_token_provider(
        credential, "https://management.azure.com/.default"
    )
    headers = {
        "Authorization": f"Bearer {token_provider()}",
        "Content-Type": "application/json",
    }

    url = (
        f"https://management.azure.com{project_resource_id}"
        f"/connections/{connection_name}?api-version={ARM_CONNECTION_API_VERSION}"
    )
    body = {
        "name": connection_name,
        "type": "Microsoft.MachineLearningServices/workspaces/connections",
        "properties": {
            "authType": "ProjectManagedIdentity",
            "category": "RemoteTool",
            "target": mcp_endpoint,
            "isSharedToAll": True,
            "audience": "https://search.azure.com/",
            "metadata": {"ApiType": "Azure"},
        },
    }
    resp = requests.put(url, headers=headers, json=body, timeout=60)
    if not resp.ok:
        sys.exit(
            f"Failed to create/update project connection '{connection_name}':"
            f" {resp.status_code} {resp.text}"
        )
    log(f"Project connection '{connection_name}' -> {mcp_endpoint} ready.")
    return mcp_endpoint


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Provision the shared Foundry IQ knowledge base for NTG agents."
    )
    ap.add_argument("--kb-name", default=os.getenv("KB_NAME", DEFAULT_KB_NAME))
    ap.add_argument("--ks-name", default=os.getenv("KS_NAME", DEFAULT_KS_NAME))
    ap.add_argument("--search-index", default=os.getenv("SEARCH_INDEX_NAME"))
    ap.add_argument("--connection-name", default=os.getenv("KB_CONNECTION_NAME", DEFAULT_CONNECTION_NAME))
    ap.add_argument("--description", default=os.getenv("KB_DESCRIPTION", DEFAULT_DESCRIPTION))
    ap.add_argument("--retrieval-instructions", default=os.getenv("KB_RETRIEVAL_INSTRUCTIONS"))
    ap.add_argument("--answer-instructions",
                    default=os.getenv("KB_ANSWER_INSTRUCTIONS", DEFAULT_ANSWER_INSTRUCTIONS))
    ap.add_argument("--reasoning-effort",
                    default=os.getenv("KB_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
                    choices=["minimal", "low", "medium"])
    ap.add_argument("--skip-ks", action="store_true",
                    help="Skip knowledge source create/update")
    ap.add_argument("--skip-connection", action="store_true",
                    help="Skip project connection create/update")
    args = ap.parse_args()

    if not args.search_index:
        sys.exit("ERROR: SEARCH_INDEX_NAME (or --search-index) is required")

    project_resource_id = required_env("PROJECT_RESOURCE_ID")
    search_endpoint = required_env("SEARCH_ENDPOINT")
    aoai_endpoint = required_env("AOAI_ENDPOINT")
    aoai_deployment = required_env("AOAI_CHAT_DEPLOYMENT")
    aoai_model = required_env("AOAI_CHAT_MODEL")

    credential = DefaultAzureCredential()

    search_admin_key = os.getenv("SEARCH_ADMIN_KEY")
    if search_admin_key:
        log("Using SEARCH_ADMIN_KEY for AI Search data-plane auth.")
        index_client = SearchIndexClient(
            endpoint=search_endpoint,
            credential=AzureKeyCredential(search_admin_key),
        )
    else:
        log("Using DefaultAzureCredential for AI Search data-plane auth.")
        index_client = SearchIndexClient(endpoint=search_endpoint, credential=credential)

    if not args.skip_ks:
        ensure_knowledge_source(
            index_client=index_client,
            ks_name=args.ks_name,
            search_index_name=args.search_index,
            description=args.description,
        )
    else:
        log(f"--skip-ks set; assuming knowledge source '{args.ks_name}' exists.")

    ensure_knowledge_base(
        index_client=index_client,
        kb_name=args.kb_name,
        ks_name=args.ks_name,
        description=args.description,
        retrieval_instructions=args.retrieval_instructions,
        answer_instructions=args.answer_instructions,
        reasoning_effort_value=args.reasoning_effort,
        aoai_endpoint=aoai_endpoint,
        aoai_deployment=aoai_deployment,
        aoai_model=aoai_model,
    )

    mcp_endpoint = (
        f"{search_endpoint.rstrip('/')}/knowledgebases/{args.kb_name}"
        f"/mcp?api-version={KB_API_VERSION}"
    )
    if not args.skip_connection:
        mcp_endpoint = ensure_project_connection(
            credential=credential,
            project_resource_id=project_resource_id,
            connection_name=args.connection_name,
            search_endpoint=search_endpoint,
            kb_name=args.kb_name,
        )

    print(json.dumps({
        "kb_name": args.kb_name,
        "ks_name": args.ks_name,
        "search_index": args.search_index,
        "connection_name": args.connection_name,
        "reasoning_effort": args.reasoning_effort,
        "mcp_endpoint": mcp_endpoint,
    }, indent=2))


if __name__ == "__main__":
    main()
