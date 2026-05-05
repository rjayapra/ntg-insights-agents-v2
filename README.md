# Azure AI Foundry Classic Agent Migrator

A Python utility for migrating classic Azure AI Agents to the new versioned agent format in Azure AI Foundry.

## Overview

This tool automates the migration of classic agents to the new versioned agent system using a two-pass strategy:

- **Pass 1**: Creates or updates all new agents without `connected_agent` tools to avoid dangling references
- **Pass 2**: Rewrites `connected_agent` tools to reference the newly migrated agents, then updates the agent definitions

### Key Features

- Reads classic agents via the Azure AI Agents SDK (`AgentsClient`)
- Creates new versioned agents via REST API on your project endpoint
- Skips creation if a new agent with the same name already exists
- Preserves agent metadata and provenance information
- Handles `connected_agent` tool rewiring automatically
- Non-destructive migration (classic agents are never deleted)
- Supports dry-run mode for previewing changes

---

## Prerequisites

- Python 3.8 or higher
- An Azure AI Foundry project with existing classic agents
- Azure credentials configured (supports `DefaultAzureCredential`)

---

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd ntg-insights-agents-v2
```

### 2. Create a Virtual Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate

# On macOS/Linux:
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

The required packages are:

- `azure-ai-agents` - Azure AI Agents SDK for reading classic agents
- `azure-identity` - Azure authentication
- `python-dotenv` - Environment variable management
- `requests` - HTTP client for REST API calls

---

## Configuration

### Create a `.env` File

Create a `.env` file in the project root with your Azure AI Foundry project details:

```env
# Required: Your Azure AI Foundry project endpoint
PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<your-project-name>

# Optional: Alternative to PROJECT_ENDPOINT
PROJECT_ENDPOINT_STRING=<your-project-endpoint-string>

# Optional: API version (defaults to "v1")
NEW_AGENTS_API_VERSION=v1

# Optional: Enable verbose HTTP request/response logging
DEBUG_HTTP=1
```

| Variable | Required | Description |
|----------|----------|-------------|
| `PROJECT_ENDPOINT` | Yes | Your Azure AI Foundry project endpoint URL |
| `PROJECT_ENDPOINT_STRING` | No | Alternative endpoint string (fallback if `PROJECT_ENDPOINT` is not set) |
| `NEW_AGENTS_API_VERSION` | No | API version to use (default: `v1`) |
| `DEBUG_HTTP` | No | Set to `1` for verbose HTTP logging |

### Azure Authentication

The script uses `DefaultAzureCredential` from the Azure Identity library. Ensure you are authenticated via one of the following methods:

- **Azure CLI**: Run `az login` before executing the script
- **Environment Variables**: Set `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_TENANT_ID`
- **Managed Identity**: Available when running in Azure

---

## Usage

### Dry Run (Recommended First Step)

Preview the migration without making any changes:

```bash
python migrator.py --dry-run
```

Save the output to files for review:

```bash
python migrator.py --dry-run > migration_plan.json 2> migration_debug.log
```

### Execute Migration

Run the actual migration:

```bash
python migrator.py
```

Save results to a file:

```bash
python migrator.py > migration_results.json 2> migration.log
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview changes without creating or updating agents |
| `--allow-unknown-existence` | If existence checks fail, treat agents as non-existing and proceed (use with caution as this may risk duplicates) |

---

## Output

The script outputs JSON to stdout with the following structure:

```json
{
  "project_endpoint": "https://...",
  "classic_count": 10,
  "pass1": {
    "attempted": 10,
    "created_or_updated": [...],
    "skipped_exists": [...],
    "failed": [...]
  },
  "pass2": {
    "attempted": 1,
    "updated_connected": [...],
    "skipped_missing_mapping": [...],
    "failed": [...]
  },
  "dry_run": false,
  "api_version": "v1"
}
```

Log messages are written to stderr for easy separation from results.

---

## Agent Naming Convention

New agent names are derived from classic agents using the following rules:

1. If the classic agent has `metadata.v2_id`, that value is used (without the version suffix)
2. Otherwise, the classic name is converted to a URL-friendly slug:
   - Converted to lowercase
   - Spaces and underscores become hyphens
   - Special characters are removed
   - Example: `"My Test Agent"` becomes `"my-test-agent"`

---

## Troubleshooting

### Authentication Errors

Ensure you are logged into Azure:

```bash
az login
```

### Missing Environment Variables

Verify your `.env` file exists and contains `PROJECT_ENDPOINT`:

```bash
cat .env
```

### Debug Mode

Enable verbose logging to diagnose issues:

```env
DEBUG_HTTP=1
```

### Common Issues

| Issue | Solution |
|-------|----------|
| `Missing PROJECT_ENDPOINT` | Add `PROJECT_ENDPOINT` to your `.env` file |
| `401 Unauthorized` | Run `az login` or check your credentials |
| `404 Not Found` | Verify your project endpoint URL is correct |
| `Connected agent mapping failed` | Ensure all referenced agents exist in classic format |
| `Existence check failed` | Use `--allow-unknown-existence` flag if needed (with caution) |

---

## Knowledge Base (Foundry IQ) Provisioning

`agent/create_knowledge_base.py` provisions a Foundry IQ knowledge base end-to-end on Azure AI Search and exposes it to Foundry agents as an MCP tool. It is idempotent and runs once per knowledge base.

### What it creates

1. **Search Index Knowledge Source** on `ntg-search` wrapping an existing search index.
2. **Knowledge Base** on `ntg-search` wired to the `gpt-4.1` deployment on `ntg-insights` for query planning + answer synthesis.
3. **`RemoteTool` connection** on the Foundry project pointing to the KB MCP endpoint, using `ProjectManagedIdentity`.

### Required additional `.env` values

```env
# Foundry project (already required by the agent scripts)
PROJECT_ENDPOINT=https://ntg-insights.services.ai.azure.com/api/projects/ntg-insights
PROJECT_RESOURCE_ID=/subscriptions/<sub>/resourceGroups/rg-devinsights/providers/Microsoft.CognitiveServices/accounts/ntg-insights/projects/ntg-insights

# Azure AI Search backing Foundry IQ
SEARCH_ENDPOINT=https://ntg-search.search.windows.net
SEARCH_INDEX_NAME=<existing-search-index-name>

# Azure OpenAI / AI Services deployment used by the KB for query planning
AOAI_ENDPOINT=https://ntg-insights.cognitiveservices.azure.com/
AOAI_CHAT_DEPLOYMENT=gpt-4.1
AOAI_CHAT_MODEL=gpt-4.1

# Model for the agents themselves
MODEL_NAME=gpt-4.1

# Optional KB tuning (sensible defaults applied if omitted)
KB_NAME=ntg-shared-kb
KS_NAME=ntg-shared-ks
KB_CONNECTION_NAME=ntg-shared-kb-mcp
KB_DESCRIPTION=Shared NTG knowledge base
KB_RETRIEVAL_INSTRUCTIONS=
KB_ANSWER_INSTRUCTIONS=Return the top search result and include citations to source documents.
# Use `low` for Canada East (medium is not supported in some regions)
KB_REASONING_EFFORT=low
```

> **Region note:** `medium` reasoning effort is **not supported in Canada East** as of 2025-11-01-preview (returns `FeatureNotSupportedInService`). Use `low` (default) or `minimal` instead. `low` works fine for single-knowledge-source setups.

### Required RBAC

Three principals are involved end-to-end. All assignments are at resource scope.

| Principal | Resource | Role | Why |
|---|---|---|---|
| User / SP running the scripts | `ntg-insights` (Foundry account) | **Azure AI User** | Create agents, threads, runs |
| User / SP running the scripts | `ntg-insights` (Foundry account) | **Contributor** _or_ **Azure AI Project Manager** | Create the project connection via ARM |
| User / SP running the scripts | `ntg-search` (AI Search) | **Search Service Contributor** | Create KB / KS via AAD |
| Foundry **project** managed identity (`identity.principalId` of the project) | `ntg-search` | **Search Index Data Reader** | Agent retrieves docs from the index |
| Foundry **project** managed identity | `ntg-search` | **Search Service Contributor** | Agent enumerates KB MCP tools |
| Foundry **project** managed identity | `ntg-insights` | **Cognitive Services User** _and_ **Azure AI User** | Agent invokes gpt-4.1 |
| **Search service** system-assigned MI (`identity.principalId` of `ntg-search`) | `ntg-insights` | **Cognitive Services User** _and_ **Azure AI User** | KB calls gpt-4.1 for query planning + answer synthesis |

**Required service config:**

```powershell
# 1. Enable AAD on the Search service (in addition to keys). Without this, MI tokens are rejected.
az search service update -n ntg-search -g rg-devinsights `
  --aad-auth-failure-mode http403 `
  --auth-options aadOrApiKey

# 2. Foundry account `ntg-insights` typically has `disableLocalAuth=true` already; AAD is mandatory for it.
```

**Search admin-key fallback:** if you only have control-plane (`Contributor`) access on `ntg-search`, set `SEARCH_ADMIN_KEY` in `.env` and the provisioning script uses key auth for the Search data plane instead of AAD:

```powershell
az search admin-key show --service-name ntg-search -g rg-devinsights --query primaryKey -o tsv
```

This only affects the *provisioning* script. Agent runtime always uses AAD via the project MI.

### Usage

A single shared KB is provisioned for all NTG agents. Run once per environment (dev / staging):

```powershell
python agent/create_knowledge_base.py
```

Or override any value via flags (overrides env):

```powershell
python agent/create_knowledge_base.py `
  --search-index <existing-index-name> `
  --kb-name ntg-shared-kb `
  --reasoning-effort medium
```

The script prints a JSON result with the KB MCP endpoint and connection name. Use those for the agent scripts:

```env
# Same shared KB endpoint for both agents
MCP_SERVER_LABEL=knowledge-base
MCP_SERVER_URL=https://ntg-search.search.windows.net/knowledgebases/ntg-shared-kb/mcp?api-version=2025-11-01-preview
MCP_CONNECTION_NAME=ntg-shared-kb-mcp

LESSONPLAN_AGENT_NAME=NTG-LessonPlanning-Agent
QSP_AGENT_NAME=NTG-QSP-Agent
```

### Flags

| Flag | Env equivalent | Default |
|------|----------------|---------|
| `--kb-name` | `KB_NAME` | `ntg-shared-kb` |
| `--ks-name` | `KS_NAME` | `ntg-shared-ks` |
| `--search-index` | `SEARCH_INDEX_NAME` | _(required)_ |
| `--connection-name` | `KB_CONNECTION_NAME` | `ntg-shared-kb-mcp` |
| `--description` | `KB_DESCRIPTION` | `Shared NTG knowledge base` |
| `--retrieval-instructions` | `KB_RETRIEVAL_INSTRUCTIONS` | _(none)_ |
| `--answer-instructions` | `KB_ANSWER_INSTRUCTIONS` | `Return the top search result and include citations to source documents.` |
| `--reasoning-effort` | `KB_REASONING_EFFORT` | `medium` (`minimal` \| `low` \| `medium`) |
| `--skip-ks` | — | Skip knowledge source create/update |
| `--skip-connection` | — | Skip project connection create/update |

### Notes

- The underlying Azure AI Search index must already exist and be populated. The script wraps it in a Foundry IQ `SearchIndexKnowledgeSource` but does not ingest documents.
- The index is expected to be vector-enabled (using the `text-embedding-3-small` deployment) so the KB performs hybrid (keyword + vector + semantic) retrieval.
- The KB MCP endpoint API version is pinned to `2025-11-01-preview` per current Foundry IQ docs.

---

## Smoke testing (optional)

[`agent/seed_sample_docs.py`](agent/seed_sample_docs.py) seeds 2 sample documents (a Grade 5 fractions lesson plan and a QSP overview) into the configured index. Useful for validating the full pipeline before real content lands.

```powershell
# uses SEARCH_ADMIN_KEY if set, otherwise AAD
python agent\seed_sample_docs.py
```

Then test in the Foundry portal playground (`https://ai.azure.com` → `ntg-insights` project → Agents → `NTG-LessonPlanning-Agent` → Try in playground):

- *"Give me a sample lesson plan for grade 5 math on fractions."* → should hit `sample-fractions-grade5`
- *"What is a Quality Service Plan?"* (switch to `NTG-QSP-Agent`) → should hit `sample-qsp-overview`

Delete the samples once real data is loaded:

```powershell
$key = az search admin-key show --service-name ntg-search -g rg-devinsights --query primaryKey -o tsv
$h = @{ "api-key" = $key; "Content-Type" = "application/json" }
$body = '{"value":[{"@search.action":"delete","id":"sample-fractions-grade5"},{"@search.action":"delete","id":"sample-qsp-overview"}]}'
Invoke-RestMethod -Method Post -Uri "https://ntg-search.search.windows.net/indexes/oscar-multilingual-index/docs/index?api-version=2024-11-01-preview" -Headers $h -Body $body
```

---

## Troubleshooting (KB)

| Error | Likely cause | Fix |
|---|---|---|
| `403 Forbidden` enumerating KB MCP tools | Project MI missing `Search Service Contributor` on `ntg-search`, **or** Search service is `apiKeyOnly` | Grant the role + run the `az search service update --auth-options aadOrApiKey` command above |
| `401 Unauthorized` calling `chat/completions` from KB | Search service MI missing `Cognitive Services User` + `Azure AI User` on the Foundry account | Grant both roles to `ntg-search`'s system-assigned MI |
| `'Medium' reasoning effort is not supported in this region` | Region (e.g. Canada East) does not support medium | Set `KB_REASONING_EFFORT=low` in `.env` and re-run the provisioning script |
| Agent returns `"No References available"` | Index is empty, or KB query planning failed | Run `seed_sample_docs.py` to confirm wiring; check Foundry portal trace for tool-call errors |
| `PermissionDenied` creating agent | User missing `Azure AI User` on the Foundry account | Grant the role |

---

## License

MIT License

---

## Contributing

Contributions are welcome. Please open an issue or submit a pull request.
