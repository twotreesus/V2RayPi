# Claude Code Instructions

## Language
- Communicate with the user in Chinese.
- All code, comments, and commit messages must be in English.

## Workflow
- After modifying code, do not commit automatically. Wait for the user to debug and confirm; they will explicitly ask when ready to commit.
- When summarizing changes or writing commit messages, always base them strictly on `git diff` / `git status` output — never rely on memory.
- Modify only the parts explicitly requested. If you find other areas worth optimizing, ask first before touching them.

## Code Style
- Classes and functions generally do not need comments — aim for self-explanatory naming instead.
- For complex logic (network communication, state configuration), add logs to facilitate debugging.
- For foundational concerns (logging, control flow, task scheduling), use existing framework features and libraries rather than rolling your own.

## Correctness
- Read the code thoroughly before modifying it. Prioritize one-time correctness over speed.
- For refactoring changes, scan all references and complete all modifications together to avoid compilation errors.
