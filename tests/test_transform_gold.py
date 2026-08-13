"""Gold aggregation and PRR."""


def test_pairs_are_bounded_by_report_not_global(bronze_df, make_report, make_drug, make_reaction):
    """Two drugs x three reactions in one report is six pairs - within that report only."""
    from src.transform.gold import build_drug_reaction_pairs
    from src.transform.silver import build_silver_drug, build_silver_reaction

    df = bronze_df(
        [
            make_report(
                "A",
                drugs=[make_drug("X"), make_drug("Y")],
                reactions=[make_reaction(f"R{i}") for i in range(3)],
            )
        ]
    )
    pairs = build_drug_reaction_pairs(build_silver_drug(df), build_silver_reaction(df))
    assert pairs.count() == 6


def test_concomitant_drugs_excluded_by_default(bronze_df, make_report, make_drug, make_reaction):
    """Only suspect drugs count as exposure - concomitant medications are not the signal."""
    from src.transform.gold import build_drug_reaction_pairs
    from src.transform.silver import build_silver_drug, build_silver_reaction

    df = bronze_df(
        [
            make_report(
                "A",
                drugs=[make_drug("SUSPECT", role="1"), make_drug("CONCOM", role="2")],
                reactions=[make_reaction("N")],
            )
        ]
    )
    pairs = build_drug_reaction_pairs(build_silver_drug(df), build_silver_reaction(df))
    substances = {r["active_substance"] for r in pairs.collect()}
    assert substances == {"SUSPECT"}


def test_prr_above_one_when_reaction_concentrates_in_one_drug(
    bronze_df, make_report, make_drug, make_reaction
):
    from src.transform.gold import build_drug_reaction_pairs, build_gold_signals
    from src.transform.silver import build_silver_drug, build_silver_reaction

    records = []
    # Drug X almost always reported with RASH.
    for i in range(20):
        records.append(
            make_report(f"X{i}", drugs=[make_drug("X")], reactions=[make_reaction("RASH")])
        )
    # Drug Y spread across other reactions.
    for i in range(20):
        records.append(
            make_report(f"Y{i}", drugs=[make_drug("Y")], reactions=[make_reaction(f"OTHER{i % 5}")])
        )

    df = bronze_df(records)
    pairs = build_drug_reaction_pairs(build_silver_drug(df), build_silver_reaction(df))
    signals = build_gold_signals(pairs)

    row = next(
        r
        for r in signals.collect()
        if r["active_substance"] == "X" and r["reaction_term"] == "RASH"
    )
    assert row["report_count"] == 20
    # RASH never occurs with any other drug, so cell c is zero and the
    # continuity correction is what keeps this row from vanishing.
    assert row["c"] == 0
    assert row["continuity_corrected"] is True
    assert row["prr"] is not None and row["prr"] > 1.0


def test_min_count_flag_marks_noise(bronze_df, make_report, make_drug, make_reaction):
    """A pair seen once can produce a spectacular ratio that means nothing."""
    from src.transform.gold import build_drug_reaction_pairs, build_gold_signals
    from src.transform.silver import build_silver_drug, build_silver_reaction

    records = [make_report("A", drugs=[make_drug("RARE")], reactions=[make_reaction("ODD")])]
    records += [
        make_report(f"B{i}", drugs=[make_drug("COMMON")], reactions=[make_reaction("NAUSEA")])
        for i in range(10)
    ]

    df = bronze_df(records)
    signals = build_gold_signals(
        build_drug_reaction_pairs(build_silver_drug(df), build_silver_reaction(df))
    )
    rare = next(r for r in signals.collect() if r["active_substance"] == "RARE")
    assert rare["report_count"] == 1
    assert rare["meets_min_count"] is False


def test_contingency_table_sums_to_total(bronze_df, make_report, make_drug, make_reaction):
    """a + b + c + d must equal the pair total, or the PRR denominator is wrong."""
    from src.transform.gold import build_drug_reaction_pairs, build_gold_signals
    from src.transform.silver import build_silver_drug, build_silver_reaction

    records = [
        make_report(f"R{i}", drugs=[make_drug(f"D{i % 3}")], reactions=[make_reaction(f"X{i % 4}")])
        for i in range(24)
    ]
    df = bronze_df(records)
    pairs = build_drug_reaction_pairs(build_silver_drug(df), build_silver_reaction(df))
    total = pairs.count()
    for row in build_gold_signals(pairs).collect():
        assert row["a"] + row["b"] + row["c"] + row["d"] == total
