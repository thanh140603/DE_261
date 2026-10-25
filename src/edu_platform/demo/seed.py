"""Demo reference data: organisations, courses, learners, assignments.

Names are fictional. Learner l-004 is scripted to become the at-risk learner;
org-globex has fewer than 5 learners so BR6 k-anonymity suppression is visible.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Organisation:
    id: str
    name: str


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    content_id: str
    duration_sec: int
    ordinal: int


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    org_id: str
    skill: str
    difficulty: str
    category: str
    lessons: tuple[Lesson, ...]


@dataclass(frozen=True)
class Learner:
    id: str
    name: str
    org_id: str
    course_ids: tuple[str, ...]
    advisor_id: str


@dataclass(frozen=True)
class Advisor:
    id: str
    name: str


@dataclass(frozen=True)
class TestSpec:
    id: str
    call: str  # python expression, or sql fixture name
    expected: str  # repr of expected value / rows


@dataclass(frozen=True)
class Assignment:
    id: str
    title: str
    course_id: str
    language: str
    prompt: str
    starter_code: str
    tests: tuple[TestSpec, ...]


ORGANISATIONS = (
    Organisation("org-acme", "Acme Learning"),
    Organisation("org-globex", "Globex Academy"),
)

COURSES = (
    Course(
        "c-sql-101",
        "SQL Foundations",
        "org-acme",
        "sql",
        "easy",
        "database",
        (
            Lesson("l-sql-1", "Selecting rows", "v-sql-select", 240, 1),
            Lesson("l-sql-2", "Joins", "v-sql-joins", 420, 2),
            Lesson("l-sql-3", "Grouping and aggregates", "v-sql-group", 360, 3),
        ),
    ),
    Course(
        "c-py-201",
        "Python for Data",
        "org-acme",
        "python",
        "easy",
        "programming",
        (
            Lesson("l-py-1", "Functions", "v-py-func", 300, 1),
            Lesson("l-py-2", "Lists and loops", "v-py-lists", 330, 2),
            Lesson("l-py-3", "Working with files", "v-py-files", 280, 3),
        ),
    ),
    Course(
        "c-de-301",
        "Data Engineering Basics",
        "org-acme",
        "data_engineering",
        "medium",
        "data engineering",
        (
            Lesson("l-de-1", "Batch versus streaming", "v-de-batch", 500, 1),
            Lesson("l-de-2", "Medallion architecture", "v-de-medallion", 450, 2),
        ),
    ),
    Course(
        "c-ml-301",
        "ML Engineering",
        "org-acme",
        "machine_learning",
        "hard",
        "machine learning",
        (
            Lesson("l-ml-1", "Feature pipelines", "v-ml-feature", 420, 1),
            Lesson("l-ml-2", "Model serving", "v-ml-serving", 380, 2),
        ),
    ),
    Course(
        "c-an-101",
        "Product Analytics",
        "org-acme",
        "analytics",
        "easy",
        "analytics",
        (
            Lesson("l-an-1", "Funnels", "v-an-funnel", 360, 1),
            Lesson("l-an-2", "Cohorts", "v-an-cohort", 320, 2),
        ),
    ),
    Course(
        "c-cl-401",
        "Cloud Data Pipelines",
        "org-acme",
        "cloud",
        "medium",
        "cloud",
        (
            Lesson("l-cl-1", "Object storage", "v-cl-object", 400, 1),
            Lesson("l-cl-2", "Orchestration", "v-cl-orchestration", 340, 2),
        ),
    ),
    Course(
        "c-ai-101",
        "Introduction to AI",
        "org-acme",
        "ai",
        "easy",
        "artificial intelligence",
        (
            Lesson("l-ai-1", "What is AI", "v-ai-intro", 360, 1),
            Lesson("l-ai-2", "Search and planning", "v-ai-search", 400, 2),
        ),
    ),
    Course(
        "c-ml-201",
        "Machine Learning",
        "org-acme",
        "machine_learning",
        "medium",
        "machine learning",
        (
            Lesson("l-ml-201", "Supervised learning", "v-ml-supervised", 420, 1),
            Lesson("l-ml-202", "Model evaluation", "v-ml-eval", 380, 2),
        ),
    ),
    Course(
        "c-dl-401",
        "Deep Learning",
        "org-acme",
        "deep_learning",
        "hard",
        "deep learning",
        (
            Lesson("l-dl-1", "Neural networks", "v-dl-nn", 480, 1),
            Lesson("l-dl-2", "Training deep networks", "v-dl-train", 460, 2),
        ),
    ),
    Course(
        "c-nlp-401",
        "Natural Language Processing",
        "org-acme",
        "nlp",
        "hard",
        "nlp",
        (
            Lesson("l-nlp-1", "Tokenization", "v-nlp-token", 360, 1),
            Lesson("l-nlp-2", "Transformers", "v-nlp-transformers", 440, 2),
        ),
    ),
    Course(
        "c-cv-401",
        "Computer Vision",
        "org-acme",
        "computer_vision",
        "hard",
        "computer vision",
        (
            Lesson("l-cv-1", "Convolutions", "v-cv-conv", 420, 1),
            Lesson("l-cv-2", "Object detection", "v-cv-detect", 400, 2),
        ),
    ),
    Course(
        "c-de-401",
        "Streaming Data Engineering",
        "org-acme",
        "data_engineering",
        "hard",
        "data engineering",
        (
            Lesson("l-des-1", "Kafka streams", "v-des-kafka", 420, 1),
            Lesson("l-des-2", "Windowing", "v-des-window", 380, 2),
        ),
    ),
)

ADVISORS = (Advisor("adv-1", "Thu Nguyen"), Advisor("adv-2", "Long Tran"))

LEARNERS = (
    Learner("l-001", "An Pham", "org-acme", ("c-sql-101", "c-py-201"), "adv-1"),
    Learner("l-002", "Binh Le", "org-acme", ("c-sql-101", "c-py-201"), "adv-1"),
    Learner("l-003", "Chi Hoang", "org-acme", ("c-sql-101", "c-py-201", "c-de-301"), "adv-1"),
    Learner("l-004", "Dung Vo", "org-acme", ("c-sql-101", "c-py-201"), "adv-1"),
    Learner("l-005", "Ha Dang", "org-acme", ("c-sql-101", "c-py-201", "c-de-301"), "adv-1"),
    Learner("l-006", "Khoa Bui", "org-acme", ("c-sql-101",), "adv-1"),
    Learner("l-007", "Lan Do", "org-globex", ("c-sql-101", "c-py-201"), "adv-2"),
    Learner("l-008", "Minh Ngo", "org-globex", ("c-py-201",), "adv-2"),
    Learner("l-009", "Nam Truong", "org-globex", ("c-sql-101",), "adv-2"),
)

ASSIGNMENTS = (
    Assignment(
        "a-py-fizz",
        "FizzBuzz",
        "c-py-201",
        "python",
        "Write fizzbuzz(n) that returns a list of strings for 1..n: multiples of 3 become "
        "'Fizz', multiples of 5 'Buzz', multiples of both 'FizzBuzz'.",
        "def fizzbuzz(n):\n    result = []\n    for i in range(1, n + 1):\n        result.append(str(i))\n    return result\n",
        (
            TestSpec("t1_small", "fizzbuzz(5)", "['1', '2', 'Fizz', '4', 'Buzz']"),
            TestSpec("t2_fizzbuzz", "fizzbuzz(15)[14]", "'FizzBuzz'"),
            TestSpec("t3_empty", "fizzbuzz(0)", "[]"),
            TestSpec("t4_fizz", "fizzbuzz(9)[8]", "'Fizz'"),
            TestSpec("t5_buzz", "fizzbuzz(10)[9]", "'Buzz'"),
        ),
    ),
    Assignment(
        "a-py-even",
        "Sum of even numbers",
        "c-py-201",
        "python",
        "Write sum_even(nums) that returns the sum of the even numbers in the list.",
        "def sum_even(nums):\n    return sum(nums)\n",
        (
            TestSpec("t1_mixed", "sum_even([1, 2, 3, 4])", "6"),
            TestSpec("t2_empty", "sum_even([])", "0"),
            TestSpec("t3_negative", "sum_even([-2, -3])", "-2"),
            TestSpec("t4_zero", "sum_even([0, 1])", "0"),
            # Deliberately wrong expectation: used by the "broken test case" scenario (BR4).
            TestSpec("t5_pairs", "sum_even([2, 4])", "7"),
        ),
    ),
    Assignment(
        "a-sql-joins",
        "Students with two or more courses",
        "c-sql-101",
        "sql",
        "Tables: students(id, name), enrollments(student_id, course). Return name and the "
        "number of courses for students enrolled in at least two courses, ordered by name.",
        "SELECT s.name, COUNT(*) AS courses\nFROM students s\nJOIN enrollments e ON e.student_id = s.id\nGROUP BY s.name\nORDER BY s.name;\n",
        (
            TestSpec("t1_base", "base", "[('An', 2), ('Chi', 3)]"),
            TestSpec("t2_no_courses", "with_unenrolled", "[('An', 2)]"),
            TestSpec("t3_ties", "ties", "[('An', 2), ('Binh', 2), ('Chi', 2)]"),
        ),
    ),
)

SQL_FIXTURES: dict[str, str] = {
    "base": (
        "INSERT INTO students VALUES (1,'An'),(2,'Binh'),(3,'Chi');"
        "INSERT INTO enrollments VALUES (1,'sql'),(1,'py'),(2,'sql'),(3,'sql'),(3,'py'),(3,'de');"
    ),
    "with_unenrolled": (
        "INSERT INTO students VALUES (1,'An'),(2,'Binh'),(4,'Dung');"
        "INSERT INTO enrollments VALUES (1,'sql'),(1,'py'),(2,'sql');"
    ),
    "ties": (
        "INSERT INTO students VALUES (1,'An'),(2,'Binh'),(3,'Chi');"
        "INSERT INTO enrollments VALUES (1,'sql'),(1,'py'),(2,'sql'),(2,'py'),(3,'sql'),(3,'de');"
    ),
}
SQL_SCHEMA = "CREATE TABLE students(id INTEGER, name TEXT); CREATE TABLE enrollments(student_id INTEGER, course TEXT);"


def course(course_id: str) -> Course:
    return next(c for c in COURSES if c.id == course_id)


def learner(learner_id: str) -> Learner:
    return next(it for it in LEARNERS if it.id == learner_id)


def assignment(assignment_id: str) -> Assignment:
    return next(a for a in ASSIGNMENTS if a.id == assignment_id)


def lesson_by_content(content_id: str) -> tuple[Course, Lesson] | None:
    for c in COURSES:
        for it in c.lessons:
            if it.content_id == content_id:
                return c, it
    return None
