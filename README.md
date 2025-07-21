
# Dragonfly legal search demo

> An LLM-powered legal research tool for New Zealand legislation

This application provides an intelligent search interface for New Zealand public acts using Large Language Models (LLMs).
It combines semantic search with graph-based legal cross-references to deliver comprehensive legal research capabilities.

## Disclaimer

This code was created by an external provider as part of a research and development project.
We're sharing it here to support open access and collaboration, but it wasn't developed by the Parliamentary Counsel Office.
The code hasn't been tested for use in live or production environments, and we can’t make any promises about how well it works or how safe or reliable it is. We think it's a great example of what's possible.
But if you choose to use it, you must do so at your own risk as we’re not responsible for any problems that might result.
We recommend testing it carefully in a safe setting before using it in any important or sensitive context.”

## Overview

The system uses a unique multi-phase research approach where the LLM actively queries multiple databases to build comprehensive legal analysis:

### How it works

1. **Initial semantic search**: The LLM starts by calling the semantic database (LanceDB) to find legal text fragments that match the user's query using natural language understanding.

2. **Graph-based discovery**: The LLM then uses reference identifiers from the initial results to query the graph database (Kuzu), which maps the complex web of legal cross-references, hierarchies, and citations between different acts and provisions.

3. **Iterative research**: The LLM intelligently decides which references to follow, making additional calls to:
   - Find linked provisions (`get_linked`)
   - Discover which other laws reference the found text (`get_referrers`)
   - Search for additional relevant concepts (`get_legislation`)

4. **Real-time visibility**: Each database query and its results are displayed in real-time in the **log window**, allowing users to see exactly how the AI is building its research strategy and what legal sources it is discovering.

5. **Verification and accountability**: The system explicitly requires that every AI response includes specific references to the original legal texts that were used to generate the answer.
These references use unique identifiers (e.g., "DLM327381-3038-0") that link directly back to the source legislation. This linking allows users to verify the AI's conclusions by examining the actual legal text, ensuring accuracy and enabling adequate legal citation practices.

This approach mimics how a human legal researcher would work–-starting with initial searches, then following citations and cross-references to build a complete picture of the relevant law.
The LLM can process and synthesise information from dozens of legal sources simultaneously, while providing full transparency into its research process.

## Features

- **Semantic search**: Uses vector embeddings to find relevant legal text based on natural language queries.
- **Graph-based references**: Follows legal cross-references and citations automatically.
- **AI-powered analysis**: Employs Claude or GPT models to synthesise and explain legal information.
- **Real-time research**: Streams research progress and intermediate results
- **Citation verification**: Validates all references against the original legal database.

## Limitations

- Contains only New Zealand public acts (as of March 2025).
- Not all parts of the acts are parsed (for example, some schedules may be missing from the database).
- AI responses may contain errors and should not be considered legal advice.

## Architecture

The system consists of several key components:

- **Vector database ([LanceDB][lance])**: Stores legal text fragments with semantic embeddings.
- **Graph database ([KuzuDB][kuzu])**: Models relationships between legal sections and cross-references.
- **AI agents (using [Pydantic AI][ai])**: Coordinate research using tools to query both databases.
- **Web interface**: [Streamlit app][streamlit] for user interaction and result presentation.

### Agent configuration

The agent behaviour is configured through Markdown prompt files:

- `claude.md`: System prompt for Claude agent;
- `gpt.md`: System prompt for GPT agent (if implemented).

### Database schema

#### LanceDB (Vector database)

- **Table**: `phrases`.
- **Columns**:
  - `id`: Unique reference identifier,
  - `text`: Legal text content,
  - `vector`: Semantic embedding.

#### Kuzu (Graph database)

- **Nodes**:
  - `Fragment`: Individual legal text fragments.
  - `Section`: Legal sections containing fragments.
- **Relationships**:
  - `Child_of`: Hierarchical relationships.
  - `Refers_to`: Cross-references between legal provisions.

See the [deployment notes](deploy/README.md) for further details.

## License and copyright

License [Apache 2.0][apache]

Copyright (c) 2024–2025 Dragonfly Data Science, Wellington, New Zealand.

## Support

Please contact <help@dragonfly.co.nz> if you want to discuss any aspect of this application.

---

**Disclaimer**: This application is for research purposes only and does not constitute legal advice. Always consult with qualified legal professionals for official legal guidance.

[lance]: https://lancedb.com
[streamlit]: https://docs.streamlit.io
[kuzu]: https://kuzudb.org
[ai]: https://ai.pydantic.dev
[apache]: https://www.apache.org/licenses/LICENSE-2.0
