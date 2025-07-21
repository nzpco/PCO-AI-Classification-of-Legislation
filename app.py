import asyncio
from pathlib import Path

import logfire
import streamlit as st
import streamlit_authenticator as stauth
import structlog
import toml
from pydantic_settings import BaseSettings

from agent import AgentRunner
from model import CONFIG_DICT, AgentType, Config

logfire.configure()
logfire.instrument_openai()
logfire.instrument_anthropic()
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        logfire.StructlogProcessor(),
        structlog.dev.ConsoleRenderer(),
    ],
)
logger = structlog.get_logger()

py_toml = toml.load("pyproject.toml")
VERSION = py_toml["project"]["version"]


class AuthConfig(BaseSettings):
    model_config = CONFIG_DICT
    auth_path: Path

    @property
    def auth_file(self) -> str:
        return str(self.auth_path / "auth.yml")


@st.cache_resource
def get_auth_config() -> AuthConfig:
    return AuthConfig()  # type: ignore


TITLE = f"Public Act Search (v{VERSION})"
st.set_page_config(
    page_title=TITLE,
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items=None,
)

# TODO: we will need to upload an auth.yaml to the the disk
authenticator = stauth.Authenticate(get_auth_config().auth_file)

# Basic CSS to remove padding and style logs
css = Path("style.css").read_text()
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
# script = Path("script.js").read_text()
# st.markdown(f"<style>{css}</style><script>{script}</script>", unsafe_allow_html=True)
st.title(TITLE)
st.markdown("""
> This is a demonstration of a legal search engine developed by 
> [Dragonfly Data Science](https://www.dragonfly.co.nz)
> It contains the most recent public acts of New Zealand (as at March 2025).
> The content may not be complete, and the AI-driven search may emit errors.
> All references (in green) come directly from the original XML acts.
> **This is not legal advice.**
""")

# Set up the sidebar for logs
# st.sidebar.title("Progress")
log_container = st.sidebar.container()


# Async query function - for simulation
async def do_query(query: str):
    # DISABLED: choice of agent as too confusing. GPT is hopeless.
    # agent_type = AgentType(st.session_state.agent_choice)
    agent_type = AgentType.CLAUDE
    agent = AgentRunner(query, config=Config(agent_type=agent_type))  # type: ignore
    async for next in agent.run_query():
        yield next


# Initialize state variables
if "processing" not in st.session_state:
    st.session_state.processing = False
if "results_ready" not in st.session_state:
    st.session_state.results_ready = False
if "query_text" not in st.session_state:
    st.session_state.query_text = ""
if "logs" not in st.session_state:
    st.session_state.logs = []  # Store log messages
if "result_markdown" not in st.session_state:
    st.session_state.result_markdown = ""


# Callback to handle form submission
def handle_submit():
    st.session_state.query_text = st.session_state.query_input
    st.session_state.processing = True
    st.session_state.logs = []  # Clear previous logs


# Callback to reset for new search
def new_search():
    st.session_state.processing = False
    st.session_state.results_ready = False
    st.session_state.query_input = ""
    # Note: We don't clear logs here to keep them visible
    st.session_state.result_markdown = ""


# Create placeholders for main content components
form_placeholder = st.empty()
spinner_placeholder = st.empty()
success_placeholder = st.empty()
results_placeholder = st.empty()

with log_container:
    st.markdown("# Logging Window")


def post_login(dct):
    user = dct.get("username")
    email = dct.get("email")
    logfire.info(f"user logged in {user}, {email}")


if not st.session_state.get("authentication_status"):
    try:
        res = authenticator.login(callback=post_login)
    except Exception as e:
        st.error(e)

    if st.session_state.get("authentication_status") is False:
        st.error("Username/password is incorrect")
    elif st.session_state.get("authentication_status") is None:
        st.warning("Please enter your username and password")

elif not st.session_state.processing and not st.session_state.results_ready:
    with form_placeholder.container(), st.form("my_form"):
        st.text_input("Enter your Query:", key="query_input")
        # DISABLED: choice of agent as too confusing. GPT is hopeless.
        # agent = st.radio(
        #     "choice of llm",
        #     ["claude", "gpt"],
        #     captions=[
        #         "anthropic claude 3.7",
        #         "openai gpt-4.1",
        #     ],
        #     key="agent_choice",
        # )
        submit_button = st.form_submit_button("Submit", on_click=handle_submit)

# processing state
elif st.session_state.processing and not st.session_state.results_ready:
    # clear the form
    form_placeholder.empty()
    ss = st.session_state

    # show spinner in main content area
    with (
        spinner_placeholder,
        logfire.span("Processing query", query=ss.query_text, user=ss.username),
        st.spinner("processing query (please be patient)..."),
    ):
        # process query
        async def process_query():
            # initialize the async iterator
            async_iter = do_query(ss.query_text).__aiter__()
            ss.result_markdown = "Internal error!"

            try:
                while True:
                    # try to get next chunk
                    try:
                        ongoing = await async_iter.__anext__()
                        if ongoing.complete:
                            # set the result markdown
                            ss.result_markdown = ongoing.final
                            # empty the iterator
                            while True:
                                _ = await async_iter.__anext__()

                        # we got a new chunk, add it to logs
                        # timestamp = datetime.now().strftime("%h:%m:%s")
                        ss.logs.append(ongoing.logging)

                        # update the log display in the sidebar
                        with log_container:
                            st.markdown(ongoing.logging, unsafe_allow_html=True)

                        with results_placeholder:
                            # display the markdown results
                            st.markdown(ongoing.summary, unsafe_allow_html=True)

                    except StopAsyncIteration:
                        # no more chunks, we're done processing
                        break

                # move to results state
                ss.results_ready = True

            except Exception as e:
                st.error(f"Error processing query: {e}")

        # run the async function in the main thread
        loop = asyncio.new_event_loop()
        loop.run_until_complete(process_query())
        loop.close()

    # force a rerun to move to results state
    st.rerun()

# results state
elif st.session_state.results_ready:
    # clear main content placeholders for processing items
    form_placeholder.empty()
    spinner_placeholder.empty()

    # keep logs in sidebar
    with log_container:
        # display all logs as simple markdown with small text
        for log_text in st.session_state.logs:
            st.markdown(log_text, unsafe_allow_html=True)

    # show results using pure streamlit elements
    success_placeholder.success("Research Complete!")
    with results_placeholder:
        # display the markdown results
        st.markdown(st.session_state.result_markdown, unsafe_allow_html=True)

    # new search button
    st.button("New Search", on_click=new_search)
    # download button
    st.download_button(
        label="Download Research (in Markdown)",
        data=st.session_state.result_markdown,
        file_name="document.md",
        mime="text/markdown",
    )
