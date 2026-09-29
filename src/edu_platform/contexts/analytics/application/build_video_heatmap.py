"""Use case BR7: play/pause/seek density per second of a video."""

from __future__ import annotations

from collections import defaultdict

from edu_platform.contexts.analytics.domain.model import HeatmapBucket
from edu_platform.contexts.telemetry.domain.events import LearningEvent, Verb
from edu_platform.shared_kernel.domain.ids import ContentId

_KIND = {Verb.PLAYED: "play", Verb.PAUSED: "pause", Verb.SEEKED: "seek"}


class BuildVideoHeatmap:
    def execute(
        self, events: list[LearningEvent], content_id: ContentId, duration_sec: int
    ) -> list[HeatmapBucket]:
        counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        learners: dict[int, set[str]] = defaultdict(set)
        for e in events:
            if e.content_id != content_id or e.verb not in _KIND or e.video_position is None:
                continue
            sec = min(e.video_position.second, max(0, duration_sec - 1))
            counts[sec][_KIND[e.verb]] += 1
            learners[sec].add(e.learner_pseudonym)
        return [
            HeatmapBucket(
                content_id=content_id,
                second=s,
                play_count=counts[s]["play"],
                pause_count=counts[s]["pause"],
                seek_count=counts[s]["seek"],
                unique_learners=len(learners[s]),
            )
            for s in range(duration_sec)
        ]
