"""
Seed 2 sample documents into the AI Search index for smoke-testing the KB.

Docs are embedded via AOAI text-embedding-3-small (1536-dim) and uploaded to
oscar-multilingual-index. Re-runnable: uses fixed ids, mergeOrUpload semantics.

Usage (PowerShell):
  Get-Content agent\.env | ForEach-Object { if ($_ -match '^\s*([^#=]+)=(.*)$') { [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim()) } }
  python agent\seed_sample_docs.py
"""
import os
import sys
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from openai import AzureOpenAI

load_dotenv()

SEARCH_ENDPOINT = os.environ["SEARCH_ENDPOINT"]
INDEX_NAME = os.environ["SEARCH_INDEX_NAME"]
AOAI_ENDPOINT = os.environ["AOAI_ENDPOINT"]
EMBED_DEPLOYMENT = os.environ.get("AOAI_EMBED_DEPLOYMENT", "text-embedding-3-small")
SEARCH_ADMIN_KEY = os.environ.get("SEARCH_ADMIN_KEY")  # optional

# AOAI client (AAD auth via your Contributor + Cognitive Services User)
token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)
aoai = AzureOpenAI(
    azure_endpoint=AOAI_ENDPOINT,
    azure_ad_token_provider=token_provider,
    api_version="2024-10-21",
)

# Search client — admin key if set, else AAD
if SEARCH_ADMIN_KEY:
    search = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME,
                          credential=AzureKeyCredential(SEARCH_ADMIN_KEY))
    print("[seed] Using SEARCH_ADMIN_KEY")
else:
    search = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME,
                          credential=DefaultAzureCredential())
    print("[seed] Using AAD")

DOCS = [
    {
        "id": "sample-fractions-grade5",
        "doc_id": "sample-fractions-grade5",
        "title_en": "Grade 5 Math: Introduction to Fractions",
        "title_fr": "Mathématiques 5e année : Introduction aux fractions",
        "url_en": "https://example.org/lessons/grade5-fractions",
        "url_fr": "https://example.org/lessons/grade5-fractions-fr",
        "filepath_en": "lessons/grade5/fractions.md",
        "filepath_fr": "lessons/grade5/fractions-fr.md",
        "metadata": "subject=math; grade=5; topic=fractions",
        "image_mapping": "",
        "content_en": (
            "Lesson plan: Introduction to Fractions for Grade 5.\n"
            "Objective: Students will identify fractions as parts of a whole, "
            "compare simple fractions with like denominators, and represent fractions "
            "using diagrams and number lines.\n"
            "Materials: fraction bars, paper plates, markers.\n"
            "Activity 1 (10 min): Discuss real-world examples of fractions (pizza slices, sharing snacks).\n"
            "Activity 2 (20 min): Use fraction bars to compare 1/2, 1/3, 1/4. "
            "Have students place them in order from smallest to largest.\n"
            "Activity 3 (15 min): Worksheet — shade diagrams to represent given fractions.\n"
            "Assessment: Exit ticket with three fraction-comparison problems.\n"
            "Differentiation: Provide pre-cut fraction circles for students who need extra support; "
            "offer mixed-number challenge for early finishers."
        ),
        "content_fr": (
            "Plan de leçon : Introduction aux fractions pour la 5e année.\n"
            "Objectif : Les élèves identifieront les fractions comme parties d'un tout, "
            "compareront des fractions simples ayant le même dénominateur et représenteront "
            "des fractions à l'aide de diagrammes et de droites numériques."
        ),
    },
    {
        "id": "sample-qsp-overview",
        "doc_id": "sample-qsp-overview",
        "title_en": "Quality Service Plan (QSP) Overview",
        "title_fr": "Aperçu du plan de service de qualité (QSP)",
        "url_en": "https://example.org/qsp/overview",
        "url_fr": "https://example.org/qsp/apercu",
        "filepath_en": "qsp/overview.md",
        "filepath_fr": "qsp/apercu-fr.md",
        "metadata": "domain=qsp; type=overview",
        "image_mapping": "",
        "content_en": (
            "A Quality Service Plan (QSP) is a structured document outlining the services a learner "
            "or client will receive over a defined period. Core sections include: "
            "(1) Goals and outcomes, (2) Services and supports, (3) Responsible providers, "
            "(4) Schedule and frequency, (5) Review and revision cadence. "
            "The QSP is reviewed at minimum every six months or when significant changes occur. "
            "All stakeholders — learner, family, educators, support staff — sign off on the plan. "
            "Annual reviews include outcome measurements against baseline."
        ),
        "content_fr": (
            "Un plan de service de qualité (QSP) est un document structuré décrivant les services "
            "qu'un apprenant ou un client recevra sur une période définie."
        ),
    },
]


def embed(text: str) -> list[float]:
    resp = aoai.embeddings.create(model=EMBED_DEPLOYMENT, input=text)
    return resp.data[0].embedding


print(f"[seed] embedding {len(DOCS)} docs via {EMBED_DEPLOYMENT}...")
for d in DOCS:
    d["contentVector"] = embed(d["content_en"])
    print(f"  - {d['id']}: vector dim={len(d['contentVector'])}")

print(f"[seed] uploading to {INDEX_NAME}...")
result = search.merge_or_upload_documents(documents=DOCS)
for r in result:
    status = "OK" if r.succeeded else f"FAIL ({r.error_message})"
    print(f"  {r.key}: {status}")

# Verify count
count = search.get_document_count()
print(f"[seed] index now has {count} docs total")
