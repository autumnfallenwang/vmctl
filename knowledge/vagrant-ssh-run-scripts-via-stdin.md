---
name: vagrant-ssh-run-scripts-via-stdin
description: Run lab commands as `... | vagrant ssh <host> -c 'bash -s'` — `-c '<quoted command>'` silently returns nothing.
metadata:
  type: feedback
---

To run a command on a testenv VM, pipe it in as a script rather than passing it as an argument:

```sh
printf 'du -sh /var/log\n' | vagrant ssh ig1 -c 'bash -s'
# or, for anything non-trivial:
vagrant ssh ig1 -c 'bash -s' < /path/to/script.sh
```

Passing the command directly — `vagrant ssh ig1 -c "du -b /path/* | sort -rn | head"` — frequently exits 0 with **no output at all**, which reads exactly like "the files don't exist" and sends you debugging the wrong thing.

**Why:** the argument to `-c` is re-quoted on its way through `vagrant` into the ssh command line, so globs, pipes, redirects and nested quotes get mangled or swallowed. Silence, not an error, is the failure mode — during M12 this cost two dead tool calls and briefly looked like the AM/DS logs had vanished. Piping to `bash -s` sends the script over stdin, untouched.

**How to apply:** use the `bash -s` form for every lab probe; write longer probes to a file first and redirect. Prefer `vagrant ssh` over `sshpass` for the Rocky 9 lab boxes — the `vagrant` user has passwordless sudo, while the `vmctl` login does not. Remember `vagrant` commands must run from `testenv/infra/` (or use an absolute path), and the shell's working directory persists between tool calls. See [[ig-config-gotchas]], [[ig-test-environment]].
