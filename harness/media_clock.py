"""One overlap/rate calculation for picture, speech, motion and sound cues."""
import math


def composition_clock(durations, fps=30, transition=.30, speed=1.15):
    if (not durations or fps <= 0 or not .5 <= speed <= 2 or not 0 <= transition <= 1
            or any(not math.isfinite(d) or d <= 0 for d in durations)):
        raise ValueError("Invalid composition timebase")
    overlaps = [math.floor((min(transition, a / 3, b / 3) + 1e-8) * fps) / fps
                for a, b in zip(durations, durations[1:])]
    starts, transitions, elapsed = [0.0], [], durations[0]
    for index, overlap in enumerate(overlaps, 1):
        offset = elapsed - overlap
        starts.append(offset)
        transitions.append({"from_scene": index - 1, "to_scene": index,
                            "start": offset / speed, "end": elapsed / speed,
                            "duration": overlap / speed, "type": "dissolve" if overlap else "cut"})
        elapsed += durations[index] - overlap
    return {"playback_speed": speed, "source_duration": elapsed, "expected_duration": elapsed / speed,
            "transition_duration": transition, "scene_starts": starts,
            "overlaps": overlaps, "transitions": transitions}
