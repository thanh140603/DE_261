-- Share of telemetry rejected to the DLQ in the window, in basis points (warn above 5 %).
SELECT CASE WHEN raw.n = 0 THEN 0
            WHEN dlq.n * 10000 / raw.n > 500 THEN CAST(dlq.n * 10000 / raw.n AS BIGINT) ELSE 0 END AS violations
FROM (SELECT count(*) AS n FROM bronze.telemetry_raw
      WHERE ingest_date BETWEEN DATE'${window_start}' AND DATE'${window_end}') raw
CROSS JOIN (SELECT count(*) AS n FROM bronze.telemetry_dlq
      WHERE ingest_date BETWEEN DATE'${window_start}' AND DATE'${window_end}') dlq;
