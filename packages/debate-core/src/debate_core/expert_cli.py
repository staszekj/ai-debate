import argparse
import asyncio

from debate_core.director import DirectorChannel
from debate_core.graph import build_graph, initial_state
from debate_core.mcp_service import ROLES, make_expert_deps


async def run(question: str) -> None:
    graph = build_graph(make_expert_deps(DirectorChannel()))
    async for event in graph.astream(initial_state(question), stream_mode="custom"):
        if event["type"] == "research_start":
            print(f"Wikipedia: {event['query']}", flush=True)
        elif event["type"] == "research_end":
            for source in event["sources"]:
                print(f"  {source['title']}: {source['url']}")
        elif event["type"] == "turn_end":
            print(f"{ROLES[event['speaker']]}: {event['text']}\n", flush=True)
        elif event["type"] == "summary":
            print(f"Podsumowanie: {event['text']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Psy kontra Koty")
    parser.add_argument("question")
    question = parser.parse_args().question.strip()
    if not 1 <= len(question) <= 2000:
        parser.error("question must have 1 to 2000 characters")
    asyncio.run(run(question))