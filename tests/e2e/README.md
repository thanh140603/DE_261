# End-to-end (TODO)

Full local stack: seed OLTP -> Debezium -> Flink risk job -> Kafka alert -> notification
service -> in_app sender fake. Asserts one notification per at-risk learner within 60 s.
