from __future__ import annotations

import pytest

from hawk.scoring.baseline import MIN_MATCHES, score_text, sentence_matches


def signs(sentence: str) -> list[int]:
    return [m.sign for m in sentence_matches(sentence)]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Inflation has risen sharply.", [1]),
        ("Unemployment has fallen.", [1]),  # less slack is hawkish
        ("Demand is weak.", [-1]),
        ("The risks are to the upside.", [1]),
        ("We cut Bank Rate and expanded quantitative easing.", [-1, -1]),
        ("The margin of spare capacity has narrowed.", [1]),
        ("There is little spare capacity.", [1]),  # negated dovish phrase
        ("There is no need to raise Bank Rate.", [-1]),  # negated hawkish phrase
        ("Inflation is unlikely to rise.", [-1]),  # negator between concept and direction
        ("The weather was pleasant.", []),
    ],
)
def test_sentence_matches(sentence: str, expected: list[int]) -> None:
    assert signs(sentence) == expected


def test_net_index_scaled_to_two() -> None:
    hawkish = "Inflation has risen. Wage growth is strong. Upside risks have grown."
    assert score_text(hawkish).stance == 2.0
    mixed = "Inflation has risen. Demand is weak. Wage growth is strong. Growth has slowed."
    assert score_text(mixed).stance == 0.0
    dovish = "Demand is weak. Growth has slowed. Downside risks dominate. Inflation is subdued."
    result = score_text(dovish)
    assert result.stance == -2.0 and result.dovish == 4 and result.hawkish == 0


def test_too_few_matches_scores_zero() -> None:
    result = score_text("Inflation has risen.")
    assert result.hawkish + result.dovish < MIN_MATCHES
    assert result.stance == 0.0


def test_relevance_flag() -> None:
    assert score_text("Bank Rate, inflation and monetary policy. " * 5).is_relevant
    assert not score_text("Banknotes and payment systems are being modernised. " * 5).is_relevant
