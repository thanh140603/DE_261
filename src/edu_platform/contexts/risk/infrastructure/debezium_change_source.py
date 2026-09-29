"""ChangeEventSource adapter: decode Debezium envelope (before/after/op/ts_ms/source.lsn).

Content (TODO): unwrap, keep op in {c,u,d}, order by source.lsn per key, then hand
``(table, row, at)`` to SignalRules.from_row_change (domain) - no logic lives here.
"""

# TODO
