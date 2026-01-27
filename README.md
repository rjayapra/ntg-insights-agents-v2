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

## License

MIT License

---

## Contributing

Contributions are welcome. Please open an issue or submit a pull request.
