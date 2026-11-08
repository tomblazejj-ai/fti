"""Checking AI answers (app/ai/validate.py): numbers must come from the facts in any notation,
cited fact ids must exist, and the JSON must match the task's schema."""

from app.ai import tasks, validate

FACTS = [
    {"id": "F1", "co": "Poslední cena", "hodnota": 3875.49, "zdroj": "x"},
    {"id": "F2", "co": "Fundamentální skóre", "hodnota": -4, "zdroj": "x", "text": "Rozsah −10 až +10."},
    {"id": "F3", "co": "Složka skóre: Úrokové sazby", "hodnota": -2, "zdroj": "x",
     "text": "2letý výnos 4,61 % vs. sazba Fedu 3,88 %"},
    {"id": "F4", "co": "Titulek zprávy", "hodnota": "Gold breaks 3,886 floor to new YTD low", "zdroj": "FXStreet"},
    {"id": "F5", "co": "Volná pracovní místa", "hodnota": "x", "zdroj": "kalendář", "text": "očekávání 7.11M, minule 7.08M"},
]


def test_numbers_from_facts_pass_in_any_notation():
    text = ("Cena 3 875,49 a zaokrouhleně 3 875; skóre −4 a -4; výnos 4,61 % (4,6 %), Fed 3.88 %; "
            "zlato pod 3,886 i 3 886 i 3886.0; JOLTS 7,11 mil. vs 7.08")
    assert validate.unknown_numbers({"t": text}, FACTS) == []


def test_invented_numbers_are_caught():
    bad = validate.unknown_numbers({"t": "Cíl 3 950 a podpora 3 880, RSI 71,3."}, FACTS)
    assert bad == ["3 950", "3 880", "71,3"]


def test_ids_times_dates_and_compound_words_are_not_market_numbers():
    text = "Podle F3 a F12 v 14:30, dne 3. 11. 2026 (2026-11-03), 2letý výnos, 200denní průměr, 3 faktory."
    assert validate.unknown_numbers({"t": text}, FACTS) == []


def test_schema_and_fact_ids():
    good = {"shrnuti": "a", "bias": "b", "pro": [{"text": "x", "fakta": ["F1"]}], "proti": [], "sledovat": [],
            "chybi": [], "jistota": "střední"}
    assert validate.validate(good, tasks.MARKET_SCHEMA, FACTS)["ok"] is True
    bad = {**good, "jistota": "jistě", "navic": 1, "pro": [{"text": "x", "fakta": ["F99"]}]}
    del bad["bias"]
    r = validate.validate(bad, tasks.MARKET_SCHEMA, FACTS)
    assert r["ok"] is False and r["unknown_facts"] == ["F99"]
    assert any("bias: chybí" in e for e in r["schema"]) and any("navic: navíc" in e for e in r["schema"])
    assert any("jistota: nepovolená" in e for e in r["schema"])
