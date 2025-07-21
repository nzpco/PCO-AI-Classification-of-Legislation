# Deployment notes

This is a [streamlit][sl] app deployed on [fly.io][fly].

## Fly deployment

Configuration is in the `fly.toml` file.
You need to have access to Dragonfly's account to deploy.
Use the [fly CLI][cli] to [deploy the app][deploy].

## Local development and testing

Local testing, and testing in Docker can be via the [justfile][just] located in the root of the repository.
You need to create a `.env` or `_env` file in the root of the repository, with the following variables:

```bash
LANCE_PATH=/some/path
KUZU_PATH=/some/path
AUTH_PATH=/some/path
```

You will also need an ANTHROPIC_API_KEY and a OPENAI_API_KEY.
These keys can be set in the `.env` file too, if you are using [direnv][direnv] (recommended).

Note that for deployment, these API keys are set using the `flyctl secrets` command, so they are not in the `.env` file.

## Syncing databases

This app requires access to [lance][lance] and [kuzu][kuzu] databases built using PCO xml data.
These databases need to be synced to the fly volumes.
Each fly machine has its own volume, so the databases need to be copied to each machine.
There is a `just` script for this step.
The script uses the [rysnc][rsync] scripts in this folder.

## Enabling authentication

Authentication to the [streamlit][sl] app uses the [streamlit-authenticator plugin][auth].
The page provides a yaml file that can be used as a template for auth configuration (users and passwords).
These files need to be rysnced to the fly volumes, as above.
It will hash the passwords, so you can use plain text passwords in the initial yaml file.
The locations are in the fly.toml `env` section, and mirror those set above in the `.env` file.

[sl]: https://docs.streamlit.io
[auth]: https://github.com/mkhorasani/Streamlit-Authenticator
[fly]: https://fly.io
[just]: https://github.com/casey/just
[direnv]: https://direnv.net
[rsync]: https://rsync.samba.org
[lance]: https://lancedb.com
[kuzu]: https://kuzudb.org
[deploy]: https://fly.io/docs/launch/deploy/
[cli]: https://fly.io/docs/flyctl/
