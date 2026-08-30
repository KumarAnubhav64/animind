"""Tests for the Researcher agent and web-search tool."""

from app.agents.researcher import ResearchBrief, brief_to_text
from app.tools.websearch import search_multi


def test_search_multi_deduplicates_and_caps():
    queries = [
        "fourier transform intuition",
        "fourier transform common misconception",
    ]
    results = search_multi(queries, per_query=4)
    hrefs = [r["href"] for r in results]
    assert len(hrefs) == len(set(hrefs)), "results must be deduplicated by URL"
    assert len(results) <= 10
    for item in results:
        assert item["href"]
        assert item["title"]


def test_brief_to_text_renders_sections():
    brief = ResearchBrief(
        key_facts=["Fourier transform converts time domain to frequency domain."],
        analogies=["Wind the signal around a circle; speed of winding = frequency."],
        misconceptions=["That 'frequency' means only pure sine waves."],
        sources=["https://betterexplained.com/"],
    )
    text = brief_to_text(brief)
    assert "Facts to get right" in text
    assert "Useful analogies" in text
    assert "Common misconceptions" in text
    assert "betterexplained" in text


def test_brief_to_text_handles_empty_and_none():
    assert brief_to_text(None) == ""
    assert brief_to_text({}) == ""


def test_brief_to_text_accepts_dict():
    text = brief_to_text({"key_facts": ["a"], "sources": ["u"]})
    assert "- a" in text
    assert "- u" in text
