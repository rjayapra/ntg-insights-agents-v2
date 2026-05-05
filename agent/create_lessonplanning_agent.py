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
AGENT_NAME = os.environ["LESSONPLAN_AGENT_NAME"]
MODEL_NAME = os.environ["MODEL_NAME"]

SYSTEM_INSTRUCTIONS = "You are a helpful assistant that must use the knowledge base to answer the questions from user. You must never answer from your own knowledge under any circumstances. \n" + \
"Every answer must always provide annotations for using the knowledge base and render them as: `【message_idx:search_idx†source_name】` \n " + \
"If you cannot find the answer in the provided knowledge base you must respond with \"No References available\". "

# Create clients to call Foundry API
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()

# [START tool_declaration]
# MCP_SERVER_URL should be the Foundry IQ knowledge base MCP endpoint, e.g.
#   https://<search>.search.windows.net/knowledgebases/ntg-lessonplan-kb/mcp?api-version=2025-11-01-preview
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
