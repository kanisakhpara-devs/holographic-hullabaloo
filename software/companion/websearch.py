"""Optional web lookup for time-sensitive questions (setting web_search, off by default).

Only questions that look time-sensitive are searched (release dates, prices, news, who currently holds
a job, scores...). Uses DuckDuckGo through the `ddgs` package: no API key. Needs internet, adds ~1 s.
The question text is sent to DuckDuckGo, so this stays off unless he turns it on.
"""
import logging, re

log = logging.getLogger("hullabaloo.web")

TIME_RX = re.compile(
    r"\b(latest|newest|current(ly)?|right now|today|tonight|yesterday|tomorrow|this (week|month|year)|last (week|month|year)|"
    r"recent(ly)?|news|price|cost|how much is|release[sd]?|come out|came out|coming out|out yet|launch\w*|announce\w*|"
    r"score|won|winner|who is the|who's the|president|prime minister|ceo|weather|still alive|died|20[2-3]\d)\b", re.I)


def needs_search(text: str) -> bool:
    return bool(text) and len(text) < 300 and bool(TIME_RX.search(text))


def search(query: str, n: int = 3):
    """-> [{"title", "body", "href"}], [] on any failure."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS      # older package name
        except ImportError:
            log.warning("web search: ddgs not installed")
            return []
    try:
        res = list(DDGS().text(query, max_results=n))
    except Exception as ex:
        log.warning("web search failed: %s", ex)
        return []
    out = []
    for r in res[:n]:
        out.append({"title": str(r.get("title", ""))[:120], "body": re.sub(r"\s+", " ", str(r.get("body", "")))[:300],
                    "href": str(r.get("href", ""))[:200]})
    return out


def block(results):
    if not results:
        return ("You tried to look this up online and found nothing useful. Say you are not sure and your "
                "information may be out of date.")
    lines = "\n".join(f"- {r['title']}: {r['body']}" for r in results)
    return ("Web results for the latest question, searched just now (may be incomplete or wrong; prefer them over "
            "your own memory for recent facts, say you looked it up, never read links aloud):\n" + lines)
