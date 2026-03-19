---
name: researcher
description: Researches topics using HTTP and summarizes findings
triggers:
  - type: keyword
    pattern: "research"
  - type: keyword
    pattern: "look up"
  - type: keyword
    pattern: "find out"
  - type: regex
    pattern: "what is|how does|explain"
tools:
  - http_get
  - memory_append
---

When asked to research a topic:

1. Use http_get to fetch relevant web pages
2. Summarize the key findings concisely
3. Use memory_append to save important discoveries
4. Cite your sources
