# Architecture

vmctl streams and searches logs across the hosts of a single deployment over SSH, emitting JSON records labelled with the host and file they came from. It exists for the case where logs are scattered across identical servers behind a load balancer and the usual answer — Filebeat shipping into Elastic — isn't available, leaving SSH as the only way in.

## System shape

The tool is a command-line binary meant to be easy for both humans and AI agents to drive. Hosts come from a YAML config and are wrapped into profiles — for example `TEST_IG:` containing `IG1` (hostname, username, password), `IG2`, and so on — with room for whatever other metadata is needed later. A profile names one deployment; the concrete motivating case is a ForgeRock IG deployed identically on 4 servers behind a load balancer, where each host carries its own system logfile plus per-route logfiles. Connections are SSH with username/password. The password may change, and password management is the user's responsibility.

The remote side is a standard RHEL environment with basic commands like `tail` available, but with no ability to install additional tooling — so whatever runs out there must be composed from what is already present. vmctl fans out across the hosts in a profile, targets a particular log path or logfile, and brings the lines back. ForgeRock product logs are already essentially standard JSON, so vmctl does not attempt to parse arbitrary input; it adds metadata on top of each record to label its source. Streaming can go to the terminal and to a local logfile. Search output should also be JSON. The split between filtering on the remote side and filtering locally is not yet settled, and neither is the search query interface.

## Key components

Single Python package. No code exists yet — these are the responsibilities the sketch implies, not modules that have been built or named:

- **CLI entry point** — the human- and agent-facing surface; subcommands for streaming and for searching.
- **Profile config** — loads the YAML file, resolves a profile name (e.g. `TEST_IG`) to its list of hosts and their hostname/username/password plus future metadata.
- **SSH transport** — opens password-authenticated connections to each host in a profile.
- **Remote command layer** — builds the commands run on the far end, restricted to base RHEL utilities.
- **Fan-out / multiplexing** — runs against every host in the profile and merges the returned lines into one stream.
- **Envelope** — wraps each already-JSON ForgeRock record with source metadata (profile, host, logfile/route).
- **Sinks** — terminal output and a local logfile for streaming; JSON for search results.

## Constraints and non-goals

**Constraints**

- **No remote installation.** Remote hosts are stock RHEL and nothing may be installed on them. Only base utilities (`tail`, `grep`, `sed`, `awk`) are available for remote-side work — no agent, no Filebeat, nothing shipped over.
- **Deployable without uv.** uv is a development-time tool only. The project must install into a plain `venv` via `pip`, so packaging stays standard PEP 621 and the runtime has no uv dependency.
- **SSH with username/password only.** That is the connectivity that exists. Passwords may rotate.

**Non-goals**

- **Not a general-purpose log parser.** Scoped to ForgeRock product logs, which are already JSON. vmctl adds a source-labelling envelope rather than parsing arbitrary formats.
- **Not a secret store.** Password management is the user's responsibility — vmctl does not own credential storage or rotation.
- **Not a replacement for ELK.** Filebeat into Elastic remains the right answer when it's available; vmctl is the fallback for when SSH is all you have.
- **Scope is currently narrow.** vmctl is framed as a CLI for managing local VMs, but only the log streaming/search capability is in scope for now.

## Open questions

- **SSH transport.** Shell out to the system `ssh` binary (inherits the user's config, jump hosts, known_hosts) or use a library such as `asyncssh` / `paramiko`? Password auth pushes against the plain-binary option; not decided.
- **Where filtering happens.** Run `grep`/`tail` filters on the remote side to cut bytes over the wire, or ship lines back and filter locally for consistency? Likely a split, but the line isn't drawn.
- **Search query interface.** Search output should be JSON, but the query syntax is undecided — the intent is to reference existing search query tools rather than invent one.
- **Host-count scale.** No target given for how many hosts a profile is expected to fan out to (the motivating case is 4).
- **Python version floor.** Not specified. Worth pinning early, since deployment targets are RHEL.
- **Module breakdown.** The internal layout of the package hasn't been settled; see Key components for the responsibilities it needs to cover.
