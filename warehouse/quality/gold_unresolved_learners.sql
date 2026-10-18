-- Facts whose learner resolved to the unknown member (-1) in the window. Expected to be 0:
-- dim_learner creates inferred members for every referenced pseudonym.
SELECT count(*) AS violations FROM gold.fct_learning_event
WHERE event_date BETWEEN DATE'${window_start}' AND DATE'${window_end}' AND learner_key = -1;
