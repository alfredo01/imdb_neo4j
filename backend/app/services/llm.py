#import streamlit as st

import os
from dotenv import load_dotenv
load_dotenv()
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4.1-mini",temperature=0,\
                 api_key=os.getenv('OPENAI_API_KEY'))
# end::llm[]

# tag::embedding[]
# Create the Embedding model
from langchain_openai import OpenAIEmbeddings

embeddings = OpenAIEmbeddings(
    api_key=os.getenv('OPENAI_API_KEY')
)
# end::embedding[]
