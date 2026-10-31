from app.news.classifier import classify, dedup_hash


def test_hawkish_fed_headline_tags_fed_tone_bearish_for_gold():
    result = classify(
        "Fed signals hawkish stance, says rate hikes may continue",
        "Officials indicated rates could stay higher for longer.",
    )
    assert "fed_tone" in result.factor_tags
    assert result.sentiment_by_tag["fed_tone"] < 0


def test_dovish_fed_headline_tags_fed_tone_bullish_for_gold():
    result = classify(
        "Fed turns dovish, signals rate cuts ahead",
        "Policymakers discussed easing monetary policy.",
    )
    assert "fed_tone" in result.factor_tags
    assert result.sentiment_by_tag["fed_tone"] > 0


def test_gold_keyword_tags_xauusd_instrument():
    result = classify("Gold prices rise on safe-haven demand", "Bullion gained as investors sought safety.")
    assert "XAUUSD" in result.instrument_tags


def test_geopolitical_conflict_headline_is_bullish_for_gold():
    result = classify("Escalating conflict raises war fears in region", "Tensions rose sharply overnight.")
    assert "geopolitics" in result.factor_tags
    assert result.sentiment_by_tag["geopolitics"] > 0


def test_ceasefire_headline_is_bearish_for_gold_geopolitics_pillar():
    result = classify("Ceasefire agreed, de-escalation follows peace talks", "Both sides agreed to de-escalate.")
    assert "geopolitics" in result.factor_tags
    assert result.sentiment_by_tag["geopolitics"] < 0


def test_irrelevant_headline_has_no_tags_and_low_relevance():
    result = classify("Local bakery wins award for best bread", "The bakery has been open for ten years.")
    assert result.factor_tags == []
    assert result.instrument_tags == []
    assert result.relevance_score == 0.0


def test_dedup_hash_is_stable_and_case_insensitive():
    h1 = dedup_hash("Fed", "FOMC Statement", "https://example.com/a")
    h2 = dedup_hash("Fed", "fomc statement", "https://EXAMPLE.com/a")
    assert h1 == h2


def test_dedup_hash_differs_for_different_titles():
    h1 = dedup_hash("Fed", "FOMC Statement A", "https://example.com/a")
    h2 = dedup_hash("Fed", "FOMC Statement B", "https://example.com/a")
    assert h1 != h2


def test_negation_is_whole_word_only_announces_is_not_a_negation():
    # "announces" contains "no" — must NOT flip a hawkish headline to dovish
    result = classify("Fed announces rate hike of 25bps", "")
    assert result.sentiment_by_tag["fed_tone"] < 0


def test_economy_word_does_not_negate():
    result = classify("Strong economy lets Fed raise rates again", "")
    assert result.sentiment_by_tag["fed_tone"] < 0


def test_real_negation_still_flips():
    result = classify("Fed says it will not raise rates this year", "")
    assert result.sentiment_by_tag["fed_tone"] > 0


def test_hyphenated_phrase_matches():
    # real GDELT headline, 2026-09-28
    result = classify("Gold, silver ETFs tumble up to 3.6% as precious metals slide on US Fed rate-hike fears", "")
    assert "fed_tone" in result.factor_tags
    assert result.sentiment_by_tag["fed_tone"] < 0
    assert "XAUUSD" in result.instrument_tags


def test_rejected_ceasefire_reads_as_escalation():
    # real GDELT headline, 2026-09-28
    result = classify("Oil prices rise after Trump rejects Iranian ceasefire proposal", "")
    assert result.sentiment_by_tag["geopolitics"] > 0


def test_gold_coast_sports_news_is_not_about_the_metal():
    # real GDELT headline, 2026-09-28
    result = classify("Gold Coast Suns facing internal crisis as strained relationship with coach revealed", "")
    assert "XAUUSD" not in result.instrument_tags


def test_gold_medal_is_not_about_the_metal_but_gold_price_is():
    assert "XAUUSD" not in classify("Czech rower wins gold medal in Paris", "").instrument_tags
    assert "XAUUSD" in classify("Gold price hits record", "").instrument_tags


def test_department_of_war_is_not_a_war():
    # real CNBC headline + snippet, 2026-09-30
    result = classify("Boeing secures U.S. Navy deal to develop next-generation fighter jet",
                      "The Department of War and the U.S. Navy said Tuesday that it's chosen Boeing.")
    assert "geopolitics" not in result.factor_tags


def test_foreign_central_bank_rate_cut_is_not_fed_tone():
    # real fxstreet.cz item, 2026-09-30
    result = classify("Čína představila další kroky na podporu ekonomiky",
                      "Čínská centrální banka dnes představila opatření včetně snížení úrokové sazby.")
    assert "fed_tone" not in result.factor_tags


def test_english_ecb_cut_is_not_fed_tone_but_fed_cut_is():
    assert "fed_tone" not in classify("ECB announces rate cut", "").factor_tags
    assert classify("Powell signals a rate cut in December", "").sentiment_by_tag["fed_tone"] > 0
