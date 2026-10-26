# Setting it up for a team

This guide takes a team from nothing to an agent that files work on the
board they already run. It is the order to do things in; the
[README](README.md) is the reference for every key and host.

Follow it yourself, or give a coding agent this repo's URL and say "set
this up for my organization". Either way, a person answers the questions
in step 1 and handles the token, and nothing is written to the board until
step 7, after that person says yes.

## If you are the agent doing the setup

- **You are installing this, not developing it.** The repo's
  [CLAUDE.md](CLAUDE.md) is the contract for its contributors: its
  branches, secret-store items and test boards aren't yours. Follow this
  file.
- **Never handle a token.** Don't ask for one, read one, print one or
  write one to a file, and stop the person if they start to paste one into
  the chat. A config names the variable that holds a token, never the
  token. Don't run `bw get` or `bw list`, which print secrets: given an
  item's id or exact name, [server/secrets.py](server/secrets.py) reads it
  itself.
- **Write nothing to the board during setup.** `describe` only reads. When
  the board lacks something the config needs, such as a status, a label
  or a work-item type, ask the person to add it in the tracker. Don't map
  around it.
- **Never run `python -m conformance` against the team's board.** It
  creates test items, and nothing here deletes. It is for proving an
  adapter on a throwaway project, and only when the person asks.
- **Stop at each question.** Take the tracker's names from `describe`'s
  output, never from a guess. The first write is the person's, in step 7.
- **Finish with [the checklist](#done-when)**, and say which of its lines
  you couldn't check.

## 1. Ask the person

Ask these together, before anything else. Each has a default.

| Question | What it decides | Default |
|---|---|---|
| Which tracker, and where? | Plane (Cloud or self-hosted): the workspace slug from its URL, the project's identifier (such as `WEB`), and for self-hosted, its address. Jira Cloud: the site (`https://<name>.atlassian.net`), the project key, and the Scrum board's id, the number after `/boards/` in the board's URL | none |
| A software or a calendar board? | A software board runs sprints of stories and bugs. A calendar board plans dated work a cycle at a time, such as a content calendar ([calendar boards](README.md#calendar-boards)) | software |
| Where will the team chat with it? | **Claude Code**: each person runs it with their own token, so items are filed as them. **Hermes**: one account's token on a server, in a chat platform such as Discord. **The Agent SDK chat**: a terminal chat that needs a metered Anthropic API key | Claude Code |
| Where does the token live? | An environment variable, or a Bitwarden item, by its id or exact name | environment variable |
| What is the review label, and who clears it? | Every new item carries the label until the product owner signs it off | `needs-review` |
| How are sprints or cycles named? | The pattern, such as `202611` for `YYYYMM` | `YYYYMM` |
| Are there team docs to search? | Optional. Markdown published to Confluence, which the agent searches before filing a duplicate | none |

If the person would rather try it on a test project first, set that one up
first. Every step is the same, and adding the real board later is one more
file ([several boards](README.md#several-boards)).

## 2. Install

You need Python 3.12 or later, [uv](https://docs.astral.sh/uv/) and git.
Clone the repo where the team's sessions can reach it, since step 6 needs
its absolute path:

```sh
git clone https://github.com/ChrisKornaros/agentic_administration.git
cd agentic_administration
uv sync          # the server and its dependencies, into .venv
uv run pytest    # offline: no tracker or token; it ends with "passed"
```

## 3. Write the board config

```sh
mkdir -p boards                                        # git ignores it
cp examples/boards/jira.example.toml boards/<board>.toml   # or plane.example.toml, or calendar.example.toml
```

The file's name is the board's name, so pick a short one such as
`web-app`. Fill in `[connection]` from step 1, the `review` label, the
`iteration` pattern and a one-line `description`. Leave `[levels]` and
`[states]` as the template has them: step 5 fits them to the board.

`token_env` (and, for Jira, `user_env`) holds the *name* of a variable,
never a token. Keep the template's names, `PLANE_API_KEY` or
`JIRA_API_TOKEN` and `JIRA_USER`, unless the person already uses others.
The comments in each template explain every key.

## 4. Get the token to the commands

The person makes the token:

- **Plane:** an API key, made in Plane's settings, for an account that is
  a member of the project.
- **Jira Cloud:** a classic API token, from **Create API token** (not the
  scoped kind) at
  [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens),
  plus the account's email. Jira pairs the two.

Then the person picks how the token reaches your commands:

1. **Exported before your session starts.** The person exports the
   variables in a shell and starts your session from it, or restarts and
   resumes it. Your commands inherit them.
2. **Bitwarden.** The person unlocks the vault into a file only they can
   read, and tells you the item's id or exact name:

   ```sh
   umask 077; bw unlock --raw > ~/.cache/bw_session     # the person runs this
   ```

   Your commands then name the item and read the session from the file,
   never printing it: `JIRA_API_TOKEN_BW_ITEM="<item>"
   JIRA_USER_BW_ITEM="<item>" JIRA_USER_BW_FIELD=username
   BW_SESSION="$(cat ~/.cache/bw_session)" uv run …`, with the token as
   the item's password and the email as its username. For Plane, it is
   `PLANE_API_KEY_BW_ITEM`, plus `PLANE_API_KEY_BW_FIELD=<field>` when the
   key is in a custom field rather than the password.
3. **The person runs it.** You give them step 5's command, they run it in
   their own terminal and paste the output, which never holds the token.

## 5. Fit the config to the board

```sh
uv run python -m adapters.jira describe boards/<board>.toml    # Jira
uv run python -m adapters.plane describe boards/<board>.toml   # Plane
```

`describe` checks the file and lists every problem in it before it
touches the network. Then it reads the board, and never writes to it. It
prints the board as JSON: its types, states, labels, members, components
or modules, and iterations. Last, it lists every place the config doesn't
fit the board. Repeat until it ends with `config fits the board.` Until
then, every write refuses.

For each problem, take the right name from the JSON:

- **A level:** map it to the board's type by the name in `types`. On
  Jira, Feature can't be a level, so the template collapses it into a
  label, and Initiative, below Premium, into a line in the description.
  On Plane's free plan there are no work-item
  types: the `parent` and `label` forms
  ([levels](README.md#levels)) cover that, but haven't run against a live
  board yet, so tell the person.
- **A state:** each of the five states, `backlog`, `todo`,
  `in_progress`, `done` and `cancelled`, needs a status of its own. Two
  states on one status would read back as one of them (a finished item as
  cancelled), so the config check refuses it. A new Jira project has no
  Backlog or Cancelled status: the person adds them to the project's
  workflow, Cancelled in the Done category.
- **A label:** on Plane, every label the config names must already exist,
  so the person creates the missing ones. Jira makes a label the first
  time an item carries it, so a new Jira project needs none.
- **A missing type,** such as a Bug type, which a new Plane project
  lacks: the person adds it. A calendar board may leave `bug` out.

Custom fields and templates are optional. Add them once the rest fits
([dates and custom fields](README.md#dates-and-custom-fields),
[templates](README.md#templates)). Show the person the finished file.

## 6. Wire the chat

Follow the README for the host from step 1. Each one needs this clone's
absolute path, the board's config (or `boards/`, to serve every board in
it) and the token at the moment the host starts, since that is when the
server reads it:

- **Claude Code** ([the command](README.md#claude-code)): write the
  README's command into a short script for the person, such as
  `backlog.sh`, with this clone's path and the board's filled in. Keep its
  flags as they are: they keep the session to the board, frame the agent,
  and keep Claude Code's prompt before each write. The script must start
  Claude Code from an empty directory, never from this clone, so the
  developer CLAUDE.md stays out of the team's chats. It holds no token:
  the variables from step 4 (option 1 or 2) are set when it runs.
- **Hermes** ([the profile](README.md#hermes)): a profile of its own,
  the config fragment and SOUL.md. The tokens go in the profile's `.env`,
  which the person edits.
- **The Agent SDK chat** ([the command](README.md#the-claude-agent-sdk)):
  the same board and token variables, plus a metered Anthropic API key,
  never a claude.ai login.
- **Team docs** (optional): publish them
  ([publishing docs](README.md#publishing-docs-to-confluence-optional))
  and point `AGENTIC_ADMIN_KNOWLEDGE` at the publisher's config.

## 7. First run

You can't run the chat for the person, so they start it, and check two
things:

1. **A read.** "What's on the board?" The agent answers from the board. A
   token or config problem shows up here, as a tool error.
2. **One write, after their yes.** A real request they have, such as "the
   export times out when I pick a whole year". The agent asks a question
   or two, shows the drafted item and waits. After the yes, have them open
   the item in the tracker: it is in the backlog, with the review label.

Nothing is ever deleted. An item filed by mistake is cancelled, in the
chat or in the tracker.

## 8. Hand it to the team

Nobody types a command. They type what they want:

- **Anyone:** describes the problem. The agent asks, drafts, and files
  after a yes.
- **The PM:** "roll the sprint over" (`plan-sprint`), or "plan November"
  on a calendar board (`plan-cycle`).
- **The product owner:** "groom". The agent reviews what carries the
  review label, proposes fixes, and signs items off after a yes.

On Claude Code, each person needs a clone (or a shared one), uv, their
own token and the script.

## Troubleshooting

| What happens | Why, and the fix |
|---|---|
| `JIRA_API_TOKEN is not set` (or another variable) | The token isn't in that shell. See step 4 |
| Jira answers 401 | A scoped token, or the wrong email. Use a classic token and the account's email |
| `config does not fit the board` | Each line is one fix. See step 5 |
| A Jira custom field isn't found | It shows up only once it is on one of the project's screens |
| The chat has no board tools | The host started before the token was set, or the board's path is wrong. Fix it and restart the host |
| The chat offers to write code instead of filing the request | The framing line, `--append-system-prompt` in the README's command, is missing |

## Done when

- [ ] `uv run pytest` passes.
- [ ] `describe` ends with `config fits the board.`
- [ ] The chat answers a read about the board.
- [ ] One real request is on the board, with the review label, filed after
  the person's yes.
- [ ] No token is in a file, a chat or a command's output.
- [ ] The person knows what the team types (step 8), and what hasn't run
  live yet for their setup ([evidence](README.md#evidence)).
