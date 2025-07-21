import re
from enum import StrEnum, auto
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Assume the first header is the act title.c
RE_ACT = re.compile(r"^#\s*(.*?)\s*$", re.MULTILINE)
RE_HEADING = re.compile(r"^(#{1,6})\s*(.*?)\s*$")


CONFIG_DICT = SettingsConfigDict(
    # Read from .env file
    env_file=("_env", ".env"),
    # We don't care about extra keys in the _env
    extra="ignore",
)


class AgentType(StrEnum):
    GPT = auto()
    CLAUDE = auto()


class Config(BaseSettings):
    """Query an LLM at the Command Line."""

    model_config = CONFIG_DICT
    lance_path: Path
    kuzu_path: Path
    # agent_type: AgentType = AgentType.CLAUDE
    agent_type: AgentType = AgentType.GPT


# These are for the LLM agent. ---
class LLMCitation(BaseModel):
    reference: str = Field(..., description="The citation reference identifier")
    text: str = Field(
        ...,
        description=(
            "The text from the legal act, including heading and the main title."
        ),
    )

    def get_act_title(self) -> str:
        """Get the reference id from the citation."""
        match = RE_ACT.search(self.text)
        if match:
            return match.group(1)
        raise ValueError(f"Could not find act in {self.text}")

    def get_summary(self) -> str:
        """Get the reference id from the citation."""
        heading = []
        text = []
        for line in self.text.splitlines():
            if line.strip() == "":
                continue
            match = RE_HEADING.match(line)
            if match:
                heading.append(match.group(2))
            else:
                text.append(f"> {line}")
        heads = " / ".join(heading)
        texts = "\n".join(text)
        return f"{heads}\n\n{texts}"


# We use this for structured returns
class LLMResult(BaseModel):
    question: str = Field(
        ...,
        description=(
            "A clear redescription of the question "
            "being asked without losing the original intent."
        ),
    )
    response: str = Field(..., description="An informed response to the question")
    citations: list[LLMCitation] = Field(
        ..., description="a list of citations used to generate the response"
    )
