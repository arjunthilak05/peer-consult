# Security policy

peer-consult runs other AI agents on your machine. Its main security property is that **advisers
cannot act**: no tools, no shell, no file writes, no MCP, no network tools. The council writes code
only after explicit human approval, and only inside an isolated Git worktree. A way around either
property is a vulnerability.

## Reporting

Please report vulnerabilities **privately** through GitHub: open the repository's **Security** tab
and choose **Report a vulnerability**. Do not open a public issue.

Include the peer-consult version, OS, the versions of the agent CLIs involved
(`peer-consult doctor` prints them), and the smallest reproduction you can share. You should get an
acknowledgement within a few days.

## In scope

- An adviser (Claude, Codex or agy) that executes a tool, command or file write during `ask` or a
  council deliberation stage.
- Plan execution without approval, or the writer modifying files outside `authorized_files`, or
  outside its worktree.
- Bypassing the recursion guard (`PEER_CONSULT_DEPTH`), budget or size limits.
- Leaking credential files or secrets into a request packet despite refusal and redaction.
- Unauthenticated access to the office server API or WebSocket.

## Out of scope

- Vulnerabilities in the agent CLIs themselves. Report those to Anthropic, OpenAI or Google.
- Advice quality. Advisers can be wrong, and the calling agent must verify their claims.
- Exposing the office server on a non-loopback interface yourself (the CLI warns about it).

## Supported versions

Only the latest release receives security fixes.
