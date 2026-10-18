-- gold.dim_date: generated calendar 2020-01-01 .. 2035-12-31 (ISO weeks start on Monday).
INSERT OVERWRITE gold.dim_date
SELECT CAST(date_format(d, 'yyyyMMdd') AS INT)   AS date_key,
       d                                         AS date,
       weekday(d) + 1                            AS day_of_week,
       date_format(d, 'EEEE')                    AS day_name,
       weekday(d) >= 5                           AS is_weekend,
       CAST(date_trunc('WEEK', d) AS DATE)       AS week_start,
       weekofyear(d)                             AS iso_week,
       month(d)                                  AS month,
       date_format(d, 'MMMM')                    AS month_name,
       quarter(d)                                AS quarter,
       year(d)                                   AS year
FROM (SELECT explode(sequence(DATE'2020-01-01', DATE'2035-12-31', INTERVAL 1 DAY)) AS d);
