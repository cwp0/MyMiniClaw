---
name: code-review
description: Reviews code files for quality issues
triggers:
  - type: keyword
    pattern: "review"
  - type: keyword
    pattern: "code review"
  - type: regex
    pattern: "review\\s+(this|the|my)\\s+(code|file|pr)"
tools:
  - file_read
  - shell_exec
---

When asked to review code:

1. Use file_read to read the specified file
2. Analyze for:
   - Bugs and logic errors
   - Code style issues
   - Missing error handling
   - Performance concerns
3. Provide specific, actionable feedback
4. Use memory_append to record any patterns you notice
