"""Keep late source passages in context without sending unbounded page text."""
from workflows.research import article_text, evidence_excerpt


def test_article_excludes_navigation_and_executable_content():
    html = '<nav>menu</nav><main><p>Recorded evidence.</p><script>untrusted()</script><p>Second passage.</p></main>'
    assert article_text(html) == "Recorded evidence. Second passage."


def test_long_source_keeps_late_relevant_passage_and_signals_omission():
    source = "Introduction. " + "x" * 12000 + " Zhang Qian was sent in 139 BCE. " + "y" * 6000
    excerpt = evidence_excerpt(source, ["Zhang Qian"])
    assert excerpt.startswith("Introduction.")
    assert "Zhang Qian was sent in 139 BCE." in excerpt
    assert "[…]" in excerpt
    assert len(excerpt) <= 9000


def test_short_evidence_is_preserved_exactly():
    assert evidence_excerpt("Short reliable evidence.", ["reliable"]) == "Short reliable evidence."
