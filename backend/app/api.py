
from fastapi import FastAPI,Header, Security, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import base64
#from streamlit.utils import get_session_id
from pydantic import BaseModel
from typing import List,Optional,Literal
import pandas as pd
import json
import sys
from pathlib import Path
import os
import secrets
#sys.path.append(str(Path(__file__).resolve().parent.parent / "mlops/src/models"))
#sys.path.append(str(Path(__file__).resolve().parent.parent / "mlops/src/data"))
import os
print("Current Working Directory:", os.getcwd())  # Check where FastAPI is executing from
#from app.services.tools.cypher import cypher_qa_tool as generate_response
from app.services.tools.cypher_to_d3 import cypher_qa_tool as generate_response
from app.services.tools.neo4j_to_json import to_d3_format
from app.services.graph import enhanced_graph as graph


def enrich_with_pagerank(d3_data):
    """Fetch betweennessCentrality directly from Neo4j and merge into D3 node data."""
    node_ids = [n['id'] for n in d3_data['nodes']]
    if not node_ids:
        return d3_data
    results = graph.query(
        "UNWIND $ids AS nid "
        "MATCH (n) WHERE n.personId = nid OR n.movieId = nid "
        "RETURN coalesce(n.personId, n.movieId) AS id, n.betweennessCentrality AS betweennessCentrality",
        {"ids": node_ids}
    )
    pr_map = {r['id']: r['betweennessCentrality'] for r in results if r['betweennessCentrality'] is not None}
    for node in d3_data['nodes']:
        if node['id'] in pr_map:
            node['betweennessCentrality'] = pr_map[node['id']]
    return d3_data

from pydantic import BaseModel, Field
from typing import List, Optional


class ChatTurn(BaseModel):
    user: str
    bot: str

class Query(BaseModel):
    message: str
    history: list[ChatTurn] = []  # History is optional but expected as list of turns

api = FastAPI(openapi_tags=[
    {
        'name': 'Hello World',
        'description': 'This is a simple hello world endpoint'

    },
    {
        'name': 'Chat Query',
        'description': 'Query the Neo4j graph database using Cypher statements'

    },
])

# Add CORS middleware
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

latest_intermediate_steps = []

@api.get('/', tags=['Hello World'])
def get_index():
    return {'data': 'hello world'}

@api.post('/chat', tags=['Chat Query'])
async def chat(
    payload: Query,
    #session_id: Optional[str] = Header(None)
):
    """
    Chat with the agent using a message and an optional session ID.
    """
    global latest_intermediate_steps

    # Build messages history for ChatGPT
    messages = []

        # Incorporate prior turns
    for turn in payload.history:
        messages.append({"role": "user", "content": turn.user})
        messages.append({"role": "assistant", "content": turn.bot})

    # Add current message
    messages.append({"role": "user", "content": payload.message})

    # Generate response using the cypher_qa_tool  
    result = generate_response(messages)
    latest_intermediate_steps = result['intermediate_steps'][1]['context']
    return enrich_with_pagerank(to_d3_format(latest_intermediate_steps))
    

@api.get("/graph/json")
def get_graph_json():
    return enrich_with_pagerank(to_d3_format(latest_intermediate_steps))