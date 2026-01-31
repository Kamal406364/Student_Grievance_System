import os
from typing import TypedDict, List
from dotenv import load_dotenv
load_dotenv()

# =========================
# OpenAI Model Setup
# =========================

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    ToolCall,
    BaseMessage,
)

token = os.environ["GITHUB_TOKEN"]
endpoint = "https://models.github.ai/inference"

llm = ChatOpenAI(
    model="openai/gpt-4.1",
    temperature=0,
    api_key=token,
    base_url=endpoint,
)

# =========================
# Define Tools
# =========================

@tool
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

@tool
def multiply(a: int, b: int) -> int:
    """Multiply two numbers"""
    return a * b

@tool
def divide(a: int, b: int) -> float:
    """Divide two numbers"""
    return a / b

tools = [add, multiply, divide]
tools_by_name = {t.name: t for t in tools}

llm_with_tools = llm.bind_tools(tools)

# =========================
# LangGraph Setup
# =========================

from langgraph.graph import add_messages
from langgraph.func import entrypoint, task

@task
def call_llm(messages: List[BaseMessage]):
    """Call the LLM and let it decide tool usage"""
    return llm_with_tools.invoke(
        [
            SystemMessage(
                content="You are a helpful assistant that performs arithmetic using tools when needed."
            )
        ]
        + messages
    )

@task
def call_tool(tool_call: ToolCall):
    """Execute the selected tool"""
    tool_fn = tools_by_name[tool_call["name"]]
    return tool_fn.invoke(tool_call)

@entrypoint()
def agent(messages: List[BaseMessage]):
    response = call_llm(messages).result()

    while response.tool_calls:
        tool_futures = [call_tool(tc) for tc in response.tool_calls]
        tool_results = [f.result() for f in tool_futures]

        messages = add_messages(messages, [response, *tool_results])
        response = call_llm(messages).result() 

    messages = add_messages(messages, response)
    return messages

# =========================
# Run the Agent
# =========================

if __name__ == "__main__":
    messages = [HumanMessage(content="Divide 1 and 0")]
    final_messages = agent.invoke(messages)
    print(final_messages[-1].content)
