from edu_platform.br45.engine_comparison import summarize


def test_summary_uses_only_successful_measured_trials():
    summary = summarize(
        [
            {
                "suite": "BR5",
                "engine": "spark",
                "trials": [
                    {"phase": "warmup", "records": 1000, "status": "PASS", "elapsed_ms": 99},
                    {
                        "phase": "processing",
                        "records": 1000,
                        "status": "PASS",
                        "elapsed_ms": 12,
                        "events_per_second": 83,
                    },
                    {
                        "phase": "processing",
                        "records": 1000,
                        "status": "PASS",
                        "elapsed_ms": 14,
                        "events_per_second": 71,
                    },
                    {"phase": "processing", "records": 1000, "status": "TIMEOUT"},
                ],
            }
        ]
    )
    spark, flink = summary["br5"]["processing"][:2]
    assert spark["statuses"] == {"PASS": 2, "TIMEOUT": 1}
    assert (spark["min_ms"], spark["median_ms"], spark["max_ms"]) == (12, 13, 14)
    assert spark["median_events_per_second"] == 77
    assert flink["statuses"] == {"NOT_RUN": 3}
    assert flink["median_ms"] is None
