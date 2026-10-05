from langchain_core.prompts import ChatPromptTemplate

from core.chat_models import get_chat_model
from .prompts.prompt_query_analysis_agent import parser, system_prompt

query_analysis_agent = get_chat_model()

def analyze_query(query: str):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt + """{format_instructions}"""),
            ("human", "{query}"),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    chain = prompt | query_analysis_agent | parser
    return chain.invoke({"query": query}).model_dump(mode="json")
