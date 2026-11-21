import argparse
import asyncio

from debate_core.director import DirectorChannel
from debate_core.expert_graph import build_expert_graph, initial_expert_state
from debate_core.mcp_service import ROLES, make_expert_deps


async def run(question: str) -> None:
    graph = build_expert_graph(make_expert_deps(DirectorChannel()))
    async for event in graph.astream(initial_expert_state(question), stream_mode="custom"):
        if event["type"] == "research_start":
            print(f"Wikipedia ({ROLES[event['speaker']]}): {event['query']}", flush=True)
        elif event["type"] == "research_end":
            for source in event["sources"]:
                print(f"  {source['title']}: {source['url']}")
        elif event["type"] == "turn_end":
            print(f"{ROLES[event['speaker']]}: {event['text']}\n", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Psy kontra Koty")
    parser.add_argument("question")
    question = parser.parse_args().question.strip()
    if not 1 <= len(question) <= 2000:
        parser.error("question must have 1 to 2000 characters")
    asyncio.run(run(question))