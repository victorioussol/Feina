---
name: grounded-research
description: "Ground claims with Composio search (Exa, Firecrawl, Perplexity, Context7) and Hermes web tools — for Feina client agents (no X/social stack)."
version: 2.0.0
metadata:
  hermes:
    tags: [research, grounding, composio, exa, firecrawl, perplexity]
    category: research
---

# Grounded Research (Feina)

Use when the user wants answers backed by live sources, not model guesswork.

## Default stack

| Job | Tools |
|-----|--------|
| Web discovery | Composio **EXA_SEARCH** |
| Full page text | Composio **FIRECRAWL_SCRAPE** or **FIRECRAWL_SEARCH** |
| Multi-source synthesis | Composio **PERPLEXITYAI** tools |
| Library/SDK docs | Composio **Context7** |
| Fallback | Hermes `web_search` / `web_extract` |

## Composio workflow

1. `COMPOSIO_SEARCH_TOOLS` naming the toolkits you need.
2. Pass `session_id` on follow-up calls.
3. `COMPOSIO_MULTI_EXECUTE_TOOL` for parallel reads.
4. Cite sources in the reply; note tools that failed.

## Client safety

- Confirm before sending external emails or messages with research attached.
- Do not paste API keys or full secret URLs into chat.

See `references/context7-composio.md` for Context7 details.
