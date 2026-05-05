import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

load_dotenv()

PROJECT_ENDPOINT = os.environ["PROJECT_ENDPOINT"]
MCP_CONNECTION_NAME = os.environ["MCP_CONNECTION_NAME"]
MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]
MCP_SERVER_LABEL = os.environ["MCP_SERVER_LABEL"]
AGENT_NAME = os.environ["QSP_AGENT_NAME"]
MODEL_NAME = os.environ["MODEL_NAME"]

SYSTEM_INSTRUCTIONS = "You are a specialized QSP (Qualification Standards Program) assistant for the Royal Canadian Navy. " + \
"ALWAYS USE MCP TOOL TO SEARCH FOR EXACT DATA\n\n" + \
"Your role is to help users find and understand information from QSP documents using the MCP tool:\n" + \
"- Searching QSPs by NQUAL codes, roles, or topics\n" + \
"- Retrieving Performance Objectives (POs) and their details\n" + \
"- Finding Enabling Objectives (EOs) and teaching points\n" + \
"- Accessing task lists, references, and amendments\n" + \
"- Providing course details\n " + \
"Always provide clear, structured responses with relevant details from the QSP data. "

# Create clients to call Foundry API
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()

# [START tool_declaration]
# MCP_SERVER_URL should be the Foundry IQ knowledge base MCP endpoint, e.g.
#   https://<search>.search.windows.net/knowledgebases/ntg-qsp-kb/mcp?api-version=2025-11-01-preview
tool = MCPTool(
    server_label=MCP_SERVER_LABEL,
    server_url=MCP_SERVER_URL,
    require_approval="never",
    allowed_tools=["knowledge_base_retrieve"],
    project_connection_id=MCP_CONNECTION_NAME,
)
# [END tool_declaration]

# Create a prompt agent with MCP tool capabilities
agent = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(
        model=MODEL_NAME,
        instructions=SYSTEM_INSTRUCTIONS,
        tools=[tool],
    ),
)
print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")
