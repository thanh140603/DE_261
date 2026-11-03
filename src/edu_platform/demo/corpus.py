"""Synthetic lecture transcripts for the seeded LMS ``course_content`` rows (corpus bucket).

One short transcript per video in infra/postgres/init.sql, with headings so semantic
chunking has sections to respect. Used by ``edu content seed-corpus``.
"""

from __future__ import annotations

TRANSCRIPTS: dict[str, str] = {
    "v-sql-select": """# Selecting rows

A SELECT statement reads rows from a table. You list the columns you need after SELECT and name the table after FROM. Asking only for the columns you use keeps queries fast and results readable.

# Filtering with WHERE

The WHERE clause keeps only the rows that match a condition. Combine conditions with AND and OR, and use parentheses to make the order explicit. Comparisons with NULL need IS NULL, because NULL is never equal to anything.

# Sorting and limiting

ORDER BY sorts the result by one or more columns, ascending by default. LIMIT returns only the first rows, which is useful for previews and top-N questions.""",
    "v-sql-joins": """# Joins

Joins combine rows from two tables using a matching condition. The ON clause states which columns must match, usually a foreign key and the primary key it references.

# Inner joins

An inner join keeps only the rows that have a match in both tables. Students without enrolments disappear from the result of an inner join between students and enrolments.

# Outer joins

A left join keeps every row from the left table. When the right table has no matching row, its columns are filled with NULL, which lets you find students who never enrolled.""",
    "v-sql-group": """# Grouping and aggregates

GROUP BY collapses rows that share the same values into one row per group. Aggregate functions such as COUNT, SUM, AVG, MIN and MAX summarise each group.

# Filtering groups

WHERE filters rows before grouping, HAVING filters groups after aggregation. To list courses with more than ten enrolments, count per course and keep the groups with HAVING COUNT(*) > 10.""",
    "v-py-func": """# Functions

A function packages a piece of logic under a name. Define it with def, list its parameters, and return a value with return. Small functions with one job are easier to test and reuse.

# Parameters and defaults

Parameters can have default values, so callers only pass what differs. Avoid mutable defaults such as an empty list, because the same list is shared between calls.

# Return values

A function without a return statement returns None. Return early when the input is invalid instead of nesting the rest of the body in an if block.""",
    "v-py-lists": """# Lists and loops

A list holds an ordered sequence of values. Index from zero, slice with start and stop, and append to grow it.

# Iterating

A for loop visits every item of a list in order. Use enumerate when you also need the position, and zip to walk two lists together.

# Comprehensions

A list comprehension builds a new list from an existing one in a single expression, for example the squares of the even numbers. Keep comprehensions short; a loop is clearer for complex logic.""",
    "v-py-files": """# Working with files

Open a file with the open function and always close it. The with statement closes the file for you, even when an error happens inside the block.

# Reading and writing

Read the whole file with read, or iterate over the file object to process one line at a time without loading everything into memory. Open with mode w to write and a to append.

# CSV files

The csv module reads rows as lists or, with DictReader, as dictionaries keyed by the header. Pass newline='' when opening CSV files so line endings are handled correctly.""",
    "v-de-batch": """# Batch versus streaming

Batch processing handles a bounded set of data at once, for example yesterday's events, on a schedule. Streaming processes an unbounded flow of events continuously as they arrive.

# Latency and cost

Batch jobs are simple to rerun and cheap at scale but their results are only as fresh as the last run. Streaming gives low latency at the price of state management, watermarks and always-on resources.

# Late data

Events from mobile devices can arrive late. Streaming jobs use event time and watermarks to decide how long to wait; batch jobs recompute a window when late data lands.""",
    "v-de-medallion": """# Medallion architecture

The medallion architecture organises a lakehouse in layers. Bronze stores raw records exactly as received, silver stores validated and deduplicated data, and gold stores business-level models.

# Bronze and silver

Bronze is immutable and keeps the original payload for replay. Silver applies schemas, removes duplicates and pseudonymises personal data so downstream users never see raw identifiers.

# Gold and marts

Gold holds conformed dimensions and facts in a star schema. Marts built on gold answer one business question each, such as organisation progress or a video heatmap.""",
}
