"""Bounded contexts (DDD). Each package is independently deployable in spirit:

    telemetry       BR6/BR7 base   raw clickstream -> normalised, pseudonymised silver events
    grading         BR3, BR4       submission queue, sandbox log normalisation, feedback
    risk            BR5            CDC + sliding-window dropout risk scoring
    recommendation  BR2            batch + streaming features, online/offline feature store
    notification    BR1            LMS events -> rule engine -> push/in-app/email
    content         BR8 + corpus   document ingestion, chunking/embedding, cache/search sync
    analytics       BR4/6/7/8      gold marts: assessment stats, org reports, heatmaps, engagement

Contexts communicate only through domain events on Kafka or through the
lakehouse tables (published data contracts) - never by importing each other.
"""
