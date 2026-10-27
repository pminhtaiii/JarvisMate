# LifeMate Team Workflow

This page records the working agreement for the five-person competition team. It does not assign named people or define product capabilities.

## Component ownership

- Each teammate owns one or two bounded components end to end, including implementation, tests, and any UI needed for that component.
- Keep ownership boundaries clear. Before parallel work, agree which teammate owns each component and which files or interfaces they control.
- Raise cross-component dependencies early. The affected owners agree on the interface before implementation depends on it.
- Record shared interface discussions and task-specific progress in the relevant GitHub issue or pull request.
- A component owner brings their work through the team's review and integration flow. Ownership does not replace shared review of cross-component behavior.

## Shared coordination

- Use GitHub issues and pull requests as the canonical cross-teammate record for task scope, progress, interface discussion, review, and integration.
- Keep task-specific progress and interface discussion in the relevant GitHub issue or pull request. Update the short [context entry](README.md) when a settled project-wide choice changes the work for other components.
- Keep local session notes in ignored local storage. They can help an individual resume work, but are not team state or evidence available to other teammates.
- Load only the short project documents relevant to the component or decision at hand.
- The inherited `context/active_task.md` is static helper navigation, not a LifeMate assignment board. The inherited `context/progress_checker.md` has been retired; GitHub issues and PRs carry active team status.

## Memory and continuity

- Preserve durable cross-session context in the relevant GitHub issue, pull request, or active project context page.
- Inter-session memory is a future idea, not an implemented team capability. Do not rely on automatic memory transfer between sessions.
- At handoff, summarize the owned component, current state, important interface decisions, remaining work, and links to the canonical issue or pull request.
