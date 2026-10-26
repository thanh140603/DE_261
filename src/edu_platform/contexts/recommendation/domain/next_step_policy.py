"""Domain service: rule-based course recommendation (BR2).

Course-granular. The learner completes whole courses; the recommender picks
which course to *enroll in next*.

Difficulty is gated **per track family**, and the family frontier is
*contiguous*: completing a hard course without the medium in between does not
advance the frontier past the gap. Within the same readiness tier we prefer:
the same category as the most recent completion, then a related category (same
family), then a never-completed category, then title.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Recommendation

DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}

# Category -> track family. Courses in the same family are natural continuations
# of each other (e.g. AI -> ML -> DL/NLP/CV), even though their category strings differ.
CATEGORY_FAMILIES = {
    "artificial intelligence": "ai",
    "machine learning": "ai",
    "deep learning": "ai",
    "nlp": "ai",
    "computer vision": "ai",
    "database": "data",
    "data engineering": "data",
    "cloud": "data",
    "analytics": "data",
    "programming": "programming",
}


def _family(category: str) -> str:
    return CATEGORY_FAMILIES.get(category, category)


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


@dataclass(frozen=True)
class CourseRef:
    course_id: str
    title: str
    difficulty: str
    category: str


class NextStepPolicy:
    def _last_category(
        self, catalogue: list[CourseRef], completed_course_ids: list[str]
    ) -> str | None:
        if not completed_course_ids:
            return None
        by_id = {course.course_id: course for course in catalogue}
        last = by_id.get(completed_course_ids[-1])
        return last.category if last is not None else None

    def _family_frontiers(
        self, catalogue: list[CourseRef], completed_course_ids: list[str]
    ) -> dict[str, int]:
        """Contiguous frontier per family.

        The frontier is the highest difficulty level at which *every* lower level
        present in the family has also been completed at least once. A gap (e.g.
        completed hard but skipped medium) keeps the frontier below the gap.
        """
        completed = set(completed_course_ids)
        levels_by_family: dict[str, set[int]] = {}
        completed_by_family: dict[str, set[int]] = {}
        for course in catalogue:
            family = _family(course.category)
            levels_by_family.setdefault(family, set()).add(
                DIFFICULTY_ORDER.get(course.difficulty, 0)
            )
            if course.course_id in completed:
                completed_by_family.setdefault(family, set()).add(
                    DIFFICULTY_ORDER.get(course.difficulty, 0)
                )

        frontiers: dict[str, int] = {}
        for family, levels in levels_by_family.items():
            done = completed_by_family.get(family, set())
            frontier = -1
            for level in sorted(levels):
                if level in done:
                    frontier = level
                else:
                    break  # first gap
            frontiers[family] = frontier
        return frontiers

    def next_course_to_enroll(
        self,
        catalogue: list[CourseRef],
        enrolled_course_ids: list[str],
        completed_course_ids: list[str],
    ) -> Recommendation | None:
        """The single best unenrolled course to take next, or None."""
        suggestions = self.suggest_courses(catalogue, enrolled_course_ids, completed_course_ids)
        return suggestions[0] if suggestions else None

    def suggest_courses(
        self,
        catalogue: list[CourseRef],
        enrolled_course_ids: list[str],
        completed_course_ids: list[str],
    ) -> list[Recommendation]:
        """Rank unenrolled courses by per-family readiness, then affinity, then title."""
        enrolled = set(enrolled_course_ids)
        completed = set(completed_course_ids)
        last_category = self._last_category(catalogue, completed_course_ids)
        last_family = _family(last_category) if last_category is not None else None
        frontiers = self._family_frontiers(catalogue, completed_course_ids)

        completed_categories = {
            course.category for course in catalogue if course.course_id in completed
        }

        def tier(course: CourseRef) -> int:
            difficulty = DIFFICULTY_ORDER.get(course.difficulty, 0)
            frontier = frontiers[_family(course.category)]
            if difficulty == frontier + 1:
                return 0  # natural next step in this family
            if difficulty == frontier:
                return 1  # broaden at the family's level
            if difficulty < frontier:
                return 2  # backfill within the family
            return 3  # skipping too far in this family

        def affinity(course: CourseRef) -> int:
            return 0 if last_category is not None and course.category == last_category else 1

        def relatedness(course: CourseRef) -> int:
            return 0 if last_family is not None and _family(course.category) == last_family else 1

        def breadth(course: CourseRef) -> int:
            return 0 if course.category not in completed_categories else 1

        def group(t: int) -> int:
            # actionable now (next step / broaden) beats backfill beats too-advanced
            return 0 if t <= 1 else (1 if t == 2 else 2)

        unenrolled = [course for course in catalogue if course.course_id not in enrolled]
        unenrolled.sort(
            key=lambda course: (
                group(tier(course)),
                relatedness(course),
                tier(course),
                affinity(course),
                breadth(course),
                course.title,
            )
        )

        suggestions: list[Recommendation] = []
        for course in unenrolled:
            t = tier(course)
            family = _family(course.category)
            frontier = frontiers[family]
            difficulty = DIFFICULTY_ORDER.get(course.difficulty, 0)
            same_category = last_category is not None and course.category == last_category
            related = relatedness(course) == 0
            completed_above = any(
                candidate.course_id in completed
                and _family(candidate.category) == family
                and DIFFICULTY_ORDER.get(candidate.difficulty, 0) > difficulty
                for candidate in catalogue
            )

            if frontier == -1:
                reason = (
                    f"Start this track — {_article(course.difficulty)} {course.difficulty} "
                    f"{course.category} course."
                    if difficulty == 0
                    else (
                        f"Too advanced to start here — begin with the easy "
                        f"{course.category} course."
                    )
                )
            elif t == 0:
                if same_category:
                    reason = f"Continuing your {course.category} track — the next difficulty up."
                elif completed_above:
                    reason = (
                        f"Fill the gap — you skipped {_article(course.difficulty)} "
                        f"{course.difficulty} {course.category} course."
                    )
                elif related:
                    reason = (
                        f"A related next step in your track: {_article(course.difficulty)} "
                        f"{course.difficulty} {course.category} course."
                    )
                else:
                    reason = (
                        f"Continue a different track: {_article(course.difficulty)} "
                        f"{course.difficulty} {course.category} course."
                    )
            elif t == 1:
                reason = (
                    f"Broaden at your level: {_article(course.difficulty)} "
                    f"{course.difficulty} {course.category} course."
                )
            elif t == 2:
                reason = (
                    f"Backfill: {_article(course.difficulty)} {course.difficulty} "
                    f"{course.category} course you skipped."
                )
            else:
                reason = f"Too advanced — finish the intermediate {course.category} course first."

            suggestions.append(
                Recommendation(
                    course_id=course.course_id,
                    lesson_id=None,
                    title=course.title,
                    reason=reason,
                    score={0: 1.0, 1: 0.75, 2: 0.5, 3: 0.0}[t],
                )
            )
        return suggestions
