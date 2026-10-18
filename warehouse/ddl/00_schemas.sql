-- Namespaces of the lakehouse warehouse. Hive Metastore databases, exposed by Trino as
-- schemas of the `lakehouse` catalog (lakehouse.gold.fct_submission, ...).
-- Access is granted per schema (infra/trino/rules.json); the PII boundary is bronze/silver.

CREATE SCHEMA IF NOT EXISTS bronze
COMMENT 'Raw landed records exactly as received (Kafka/Debezium). Immutable, contains raw PII, restricted ACL, short retention.'
LOCATION '${lakehouse_root}/bronze';

CREATE SCHEMA IF NOT EXISTS silver
COMMENT 'Validated, deduplicated, schema-current, pseudonymised entities and events. Change Data Feed on.'
LOCATION '${lakehouse_root}/silver';

CREATE SCHEMA IF NOT EXISTS gold
COMMENT 'Kimball dimensional model: conformed dimensions (dim_*) and facts (fct_*). Pseudonymised.'
LOCATION '${lakehouse_root}/gold';

CREATE SCHEMA IF NOT EXISTS mart
COMMENT 'Business-requirement marts (BR4/BR6/BR7/BR8) read by dashboards and the API. k-anonymity enforced.'
LOCATION '${lakehouse_root}/mart';

CREATE SCHEMA IF NOT EXISTS features
COMMENT 'Offline feature store (BR2 batch branch), point-in-time by as_of_date; materialised to Redis.'
LOCATION '${lakehouse_root}/features';

CREATE SCHEMA IF NOT EXISTS ops
COMMENT 'Pipeline run log, data-quality results and incremental watermarks.'
LOCATION '${lakehouse_root}/ops';
