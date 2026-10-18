from __future__ import annotations

from hawk.scoring.textprep import clean_text, policy_density, policy_passages


def test_clean_text_removes_headers_and_numeric_debris() -> None:
    raw = (
        "Speech given by\n"
        "Inflation has been rising faster than we expected and the Committee is watching wage\n"
        "growth closely. Bank of England Page 3\n"
        "Bank of England Page 4\n"
        "1.5\n"
        "2 3 4 5\n"
        "All speeches are available online at www.bankofengland.co.uk/speeches\n"
        "Conclusion\n"
        "Policy will respond."
    )
    out = clean_text(raw)
    assert "Page" not in out
    assert "1.5" not in out
    assert "available online" not in out
    lines = out.split("\n")
    assert lines[0].startswith("Inflation has been rising") and lines[0].endswith("closely.")
    assert lines[1:] == ["Conclusion", "Policy will respond."]


def test_clean_text_keeps_short_word_lines_and_dehyphenates() -> None:
    raw = (
        "the world begins to pass you\nby.\n"
        "A wrapped line that is long enough to be text and ends with a hyph-\nenated word."
    )
    out = clean_text(raw)
    assert "pass you by." in out
    assert "hyphenated word." in out


def test_back_matter_cut_only_near_the_end() -> None:
    body = "Inflation is above target and the MPC raised Bank Rate today. " * 20
    text = f"{body}\nReferences\nSmith (2001), A paper."
    assert "Smith" not in clean_text(text)
    early = f"References\n{body}"
    assert body.strip()[:40] in clean_text(early)


def test_policy_passages_pick_policy_paragraphs_in_order() -> None:
    para_policy_1 = (
        "The MPC voted to raise Bank Rate as inflation expectations and wage growth rose. " * 3
    )
    para_other = "Our new payments system will be resilient and support innovation in fintech. " * 3
    para_policy_2 = (
        "Monetary policy must keep inflation at the 2% target; upside risks remain. " * 3
    )
    text = "\n".join([para_policy_1, para_other, para_policy_2])
    out = policy_passages(text, limit=600)
    assert "payments" not in out
    assert out.index("MPC voted") < out.index("Monetary policy must")
    assert len(out) <= 600


def test_policy_passages_respects_limit_and_falls_back() -> None:
    long_para = "Bank Rate and inflation. " * 400
    assert len(policy_passages(long_para, limit=500)) <= 502
    assert policy_passages("Nothing relevant here at all.") == "Nothing relevant here at all."


def test_policy_density() -> None:
    assert policy_density("") == 0.0
    assert policy_density("Bank Rate inflation") > policy_density("banknotes and payments")
