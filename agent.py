import ast
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import kuzu
import lancedb
from pydantic_ai import (
    Agent,
    CallToolsNode,
    ModelRequestNode,
    RunContext,
    Tool,
    UserPromptNode,
)
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.result import FinalResult
from pydantic_graph.nodes import End
from rich import print

from model import AgentType, Config, LLMCitation, LLMResult
from result import CheckedResult

type ActualAgent = Agent[Deps, LLMResult] | Agent[Deps, str]


# Wrapper for Deps for LLM agent.
@dataclass(kw_only=True)
class Deps:
    lancedb: lancedb.DBConnection
    kuzudb: kuzu.Connection
    phrase_limit: int = 20
    link_limit: int = 20


async def get_legislation(ctx: RunContext[Deps], query: str) -> list[LLMCitation]:
    """Use a semantic lookup for legislation base on phrase."""
    table = ctx.deps.lancedb.open_table("phrases")
    results = table.search(query)
    # TODO: Figure out we get double ups.
    # For now, we just ask for twice as many and then de-dup.
    lst = results.limit(ctx.deps.phrase_limit * 2).to_list()
    cites = []
    seen = set()
    for rec in lst:
        ident = rec["id"]
        if ident not in seen:
            cites.append(
                LLMCitation(
                    # act
                    reference=rec["id"],
                    text=rec["text"],
                )
            )
            seen.add(ident)
        if len(cites) >= ctx.deps.phrase_limit:
            break
    return cites


def run_cypher(
    kuzudb: kuzu.Connection, cypher: str, reference_id: str, limit: int
) -> list[LLMCitation]:
    query = kuzudb.prepare(cypher)
    results = kuzudb.execute(
        query, parameters={"key": reference_id, "link_limit": limit}
    )
    assert not isinstance(results, list)
    citations = []
    seen = set()
    while results.has_next():
        row = results.get_next()
        reference = row[0]
        text = row[1]
        if reference == reference_id:
            continue
        if reference in seen:
            continue
        cite = LLMCitation(reference=reference, text=text)
        citations.append(cite)
        seen.add(reference)
    return citations


CYPHER_LINKS = """
    MATCH (f:Fragment)-[Refers_to]->(s:Section)<-[Child_of*]-(f2:Fragment)
    where f.name = $key
    return f2.name as name, f2.phrase as phrase, f2.heads as headings
    limit $link_limit
"""


async def get_linked(ctx: RunContext[Deps], reference_id: str) -> list[LLMCitation]:
    """Use a graph database to find links to reference_id legislation."""
    citations = run_cypher(
        ctx.deps.kuzudb, CYPHER_LINKS, reference_id, ctx.deps.link_limit
    )
    return citations


CYPHER_REFERRERS = """
    MATCH (f:Fragment)-[Refers_to]->(s:Section)<-[Child_of*]-(f2:Fragment) 
    where f2.name = $key
    and split_part(f2.name, '-', 1) <> split_part(f.name, '-', 1)
    return f.name as name, f.phrase as phrase, f.heads as headings
    limit $link_limit
"""


async def get_referrers(ctx: RunContext[Deps], reference_id: str) -> list[LLMCitation]:
    """Use a graph database to find all legal text that referes to this reference_id."""
    citations = run_cypher(
        ctx.deps.kuzudb, CYPHER_REFERRERS, reference_id, ctx.deps.link_limit
    )
    return citations


def parse_dict(data: str | dict[str, Any]) -> dict[str, str]:
    """A helper function to parse a string or dict into a dict."""
    if isinstance(data, dict):
        return data
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return ast.literal_eval(data)


@dataclass
class ToolCallData:
    id: str
    md: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class OngoingResult:
    logging: str = ""
    summary: str = ""
    final: str = ""
    complete: bool = False


@dataclass
class AgentRunner:
    query: str
    config: Config
    references: dict[str, LLMCitation] = field(default_factory=dict)
    # Keep the call around till we get a return.
    tool_calls: dict[str, ToolCallData] = field(default_factory=dict)

    def get_prompt(self) -> str:
        pth = Path.cwd() / self.config.agent_type.name.lower()
        return pth.with_suffix(".md").read_text()

    def get_agent(self) -> ActualAgent:
        tools = [
            Tool(get_legislation, takes_ctx=True),
            Tool(get_linked, takes_ctx=True),
            Tool(get_referrers, takes_ctx=True),
        ]
        prompt = self.get_prompt()
        match self.config.agent_type:
            case AgentType.GPT:
                # Note that this defines the output_type
                return Agent(
                    "openai:gpt-4.1",
                    output_type=LLMResult,
                    deps_type=Deps,
                    system_prompt=prompt,
                    tools=tools,
                )
            case AgentType.CLAUDE:
                return Agent(
                    # "anthropic:claude-3-7-sonnet-latest",
                    "claude-sonnet-4-0",
                    deps_type=Deps,
                    system_prompt=prompt,
                    tools=tools,
                )
            case _:
                raise ValueError("Bad agent type")

    def get_summary(self) -> str:
        by_title = defaultdict(int)
        for v in self.references.values():
            if v.get_act_title() is not None:
                by_title[v.get_act_title()] += 1

        text = ["## Act Fragments processed"]
        for t in sorted(by_title.keys()):
            text.append(f"- {t} ({by_title[t]})")
        return "\n".join(text)

    def get_deps(self) -> Deps:
        cf = self.config
        db = lancedb.connect(cf.lance_path)
        kdb = kuzu.Database(cf.kuzu_path)
        kuzudb = kuzu.Connection(kdb)
        return Deps(lancedb=db, kuzudb=kuzudb)

    def process_user_prompt(self, txt: str) -> str:
        """Process the user prompt to remove any extra text."""
        return (
            f"### Beginning Research\n\nI'm considering the question: \n> **{txt}**\n"
        )

    def process_one_tool(self, id: str, tool_name: str, args: dict[str, str]):
        data = ToolCallData(id=id)
        md = data.md
        if tool_name == "get_legislation":
            md.append("### Searched Acts\n")
            query = args.get("query", "")
            md.append("Looking for text related to:\n")
            md.append(f"> **{query}**")
        else:
            identifier = args.get("reference_id", "")
            cite = self.references.get(identifier)
            if cite is None:
                md.append(f"The given link {identifier} appears invalid...")
            else:
                if tool_name == "get_linked":
                    md.append("### Followed links\n")
                    md.append("Looked for links found in\n")
                else:
                    md.append("### Followed Referrers\n")
                    md.append("Looking for any passages that reference this text:\n")

                md.append(cite.get_summary())
        self.tool_calls[id] = data

    def process_tool_call(self, response: ModelResponse) -> str:
        """Process the user prompt to remove any extra text."""
        text: str | None = None
        for part in response.parts:
            match part:
                case TextPart(content=content):
                    text = content
                case ToolCallPart(args=args, tool_name=tool_name, tool_call_id=id):
                    if args is None:
                        raise ValueError("Tool call args are None")
                    args = parse_dict(args)
                    self.process_one_tool(id, tool_name, args)

        markdown = []
        if text is not None:
            markdown.append(f"\n{text!s}\n")
        else:
            markdown.append("\n<div class='request'>Requesting information...</div>\n")
        return "".join(markdown)

    def process_tool_return(self, request: ToolReturnPart) -> str:
        if not isinstance(request.content, list):
            raise ValueError("Tool return is not a list")
        titles = defaultdict(int)

        for cite in request.content:
            if not isinstance(cite, LLMCitation):
                raise ValueError("Tool return is not a list of citations")
            # Keep a dict of references
            self.references[cite.reference] = cite
            titles[cite.get_act_title()] += 1

        data = self.tool_calls.pop(request.tool_call_id)

        md = data.md
        cnt = len(request.content)
        md.append(f"\n\n#### {cnt} References found\n")
        if len(titles) > 0:
            for title, count in titles.items():
                md.append(f"- {title} ({count})\n")
        else:
            md.append("No references found!\n")
        return "".join(md)

    def process_final_result(
        self,
        result: FinalResult[str] | FinalResult[LLMResult],
        db: lancedb.DBConnection,
    ) -> str:
        """Check all the references"""
        checked = CheckedResult.from_llm_result(self.query, result.output, db)
        return checked.to_markdown(css_refs="legal_ref")

    async def run_query(self) -> AsyncIterator[OngoingResult]:
        """This is our main async generation.

        It returns Markdown text for each step of the process.
        We translate between the internal nodes to progress and final text.
        """

        agent = self.get_agent()
        deps = self.get_deps()
        async with agent.iter(self.query, deps=deps) as agent_run:
            async for node in agent_run:
                match node:
                    case UserPromptNode(user_prompt=prompt):
                        if not isinstance(prompt, str):
                            raise ValueError("Prompt is not a string")
                        # This is just the initial prompt...
                        yield OngoingResult(
                            logging=self.process_user_prompt(prompt),
                            summary=self.get_summary(),
                        )
                    case ModelRequestNode(request=request):
                        # We only both looking at tool returns
                        for part in request.parts:
                            if isinstance(part, ToolReturnPart):
                                yield OngoingResult(
                                    logging=self.process_tool_return(part),
                                    summary=self.get_summary(),
                                )
                                break
                    case CallToolsNode(model_response=model_response):
                        for part in model_response.parts:
                            # only process it if we find an actual tool call
                            if isinstance(part, ToolCallPart):
                                # We only both looking at tool calls
                                yield OngoingResult(
                                    logging=self.process_tool_call(model_response),
                                    summary=self.get_summary(),
                                )
                                break
                    case End(data=data):
                        yield OngoingResult(
                            final=self.process_final_result(data, deps.lancedb),
                            complete=True,
                        )

    async def run_query_dumb(self) -> AsyncIterator[object]:
        """This returns all the raw nodes. Just for testing."""
        agent = self.get_agent()
        deps = self.get_deps()
        async with agent.iter(self.query, deps=deps) as agent_run:
            async for node in agent_run:
                yield node


async def main(query: str, agent_type: AgentType):
    from rich.markdown import Markdown

    runner = AgentRunner(query=query, config=Config(agent_type=agent_type))  # type: ignore
    async for result in runner.run_query():
        print(Markdown(result.logging))
    # async for text in runner.run_query_dumb():
    #     print(text)


if __name__ == "__main__":
    """This is just for testing."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Test running a query")
    parser.add_argument("query", help="the legal query")
    parser.add_argument(
        "--agent",
        type=AgentType,
        choices=list(AgentType),
        default=AgentType.CLAUDE,
        help="The agent to use (optional)",
    )
    args = parser.parse_args()

    asyncio.run(main(args.query, args.agent))
