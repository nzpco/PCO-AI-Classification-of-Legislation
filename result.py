import re
from typing import Self

from lancedb import DBConnection
from pydantic import BaseModel

from model import LLMResult


# We wrap the LLM result in a checked result.
# This allows us to check the citations against the database.
class CheckedCitation(BaseModel):
    reference: str
    text: str

    def demoted_text(self, n: int = 1) -> list[str]:
        """Demote all the headings in the text by n levels."""
        lines = self.text.splitlines()
        add = "#" * n
        demoted = []
        for line in lines:
            dline = add + line if line.startswith("#") else line
            demoted.append(dline)
        return demoted


# For some reason one of the acts has BILL-SCDRAFT in the reference.
# Go figure.
RE_REFERENCE = re.compile(
    r"(?:[A-Z]{1,15}\d{1,10}|BILL-SCDRAFT\d{1,10})-\d{1,7}-\d{1,5}"
)


def build_checked_citations(
    refs: set[str], db: DBConnection
) -> tuple[list[CheckedCitation], list[str]]:
    errors = []
    checked = []
    table = db.open_table("phrases")
    for ref in refs:
        cite_res = table.search().where(f"id = '{ref}'").limit(1).to_list()
        if len(cite_res) == 0:
            errors.append(f"Could not find citation: {ref}")
        else:
            # We put the text from the database into the citation.
            # The LLM is not guaranteed to do this!
            cc = CheckedCitation(reference=ref, text=cite_res[0]["text"])
            checked.append(cc)

    if len(checked) == 0:
        errors.append("No valid citations found.")
    return checked, errors


class CheckedResult(BaseModel):
    query: str
    question: str
    response: str
    errors: list[str]
    citations: list[CheckedCitation]
    was_structured: bool

    @classmethod
    def from_llm_result(
        cls, query: str, result: LLMResult | str, db: DBConnection
    ) -> Self:
        """Check the citations against the database."""
        if isinstance(result, str):
            slf = cls._build_from_str(query, result, db)
        else:
            slf = cls._build_from_result(query, result, db)
        slf.format_links()
        return slf

    @classmethod
    def _build_from_str(cls, query: str, result: str, db: DBConnection) -> Self:
        # Most important: Find the references.
        references = set(RE_REFERENCE.findall(result))
        checked, errors = build_checked_citations(references, db)

        # Try finding the question and advice.
        sections = result.split("---")
        if len(sections) == 1:
            question = sections[0].strip()
            response = ""
            errors.append("Cannot find advice.")
        else:
            question = sections[0].strip()
            response = "---".join(sections[1:])

        return cls(
            query=query,
            question=question,
            response=response,
            errors=errors,
            citations=checked,
            was_structured=False,
        )

    @classmethod
    def _build_from_result(
        cls, query: str, result: LLMResult, db: DBConnection
    ) -> Self:
        refs = {cite.reference for cite in result.citations}
        checked, errors = build_checked_citations(refs, db)
        return cls(
            query=query,
            question=result.question,
            response=result.response,
            errors=errors,
            citations=checked,
            was_structured=True,
        )

    def get_response_markdown(self) -> str:
        if self.was_structured:
            text = "\n\n".join(
                [
                    "# Question",
                    f"{self.question}",
                    "---\n# Response",
                    f"{self.response}",
                ]
            )
        else:
            text = "\n".join([self.question, "---", self.response])

        if self.errors:
            errors = ["# Errors"]
            for e in self.errors:
                errors.append(f"- {e}")
            errors.append("---")
            errors_text = "\n\n".join(errors)
            text = f"{errors_text}\n\n{text}"

        return text

    def get_references_markdown(self, css_class: str | None = None) -> str:
        txt = []
        for c in self.citations:
            if css_class:
                txt.append(f"\n<div class='{css_class}'>\n")
            else:
                txt.append("---")
            txt.append(f"## {c.reference}")
            txt.extend(c.demoted_text(2))
            if css_class:
                txt.append("</div>\n")

        return "\n".join(txt)

    def to_markdown(self, css_refs: str | None = None) -> str:
        return (
            self.get_response_markdown()
            + "\n\n"
            + self.get_references_markdown(css_refs)
        )

    def format_links(self):
        """Format references in the text as markdown links."""
        # First, find all references in the text
        text = self.response
        references = RE_REFERENCE.finditer(text)

        def transform_anchor(text: str) -> str:
            # We need to transform the text into an anchor
            # This follows the way that streamlit does it.
            # Replace different dash types with ASCII hyphen-minus "-"
            text = re.sub(r"[\u2013\u2014\u2212\u2012\u2010\u2043]", "-", text)
            # Lowercase all letters
            text = text.lower()
            # Add dash between any initial letter prefix and the first digit block
            text = re.sub(r"^([a-z]+)(\d+)", r"\1-\2", text)
            return text

        # Process the text from end to beginning to avoid offset issues
        # when making multiple replacements
        replacements = []
        for match in references:
            start, end = match.span()
            ref = match.group()
            anchor = transform_anchor(ref)

            # Check if the reference is already in brackets
            pre_char = text[start - 1 : start] if start > 0 else ""
            post_char = text[end : end + 1] if end < len(text) else ""

            if pre_char == "[" and post_char == "]":
                # Already in brackets, just add the link
                replacements.append((start - 1, end + 1, f"[{ref}](#{anchor})"))
            else:
                # Not in brackets, add brackets and link
                replacements.append((start, end, f"[{ref}](#{anchor})"))

        # Sort replacements in reverse order (from end to beginning)
        replacements.sort(key=lambda x: x[0], reverse=True)

        # Apply replacements
        result = text
        for start, end, replacement in replacements:
            result = result[:start] + replacement + result[end:]

        self.response = result
