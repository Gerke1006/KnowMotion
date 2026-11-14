# History director v2 implementation contract

This is a reusable production protocol, not a lesson or acceptance-run script.

## Agent data

`HistoryScript`: `{title, segments: [{id, narration, source_ids, intent}]}`.
The model writes 5–8 segments, around 440 Chinese characters total (380–480 accepted).
There is no prescribed topic-specific story order. Sources are retrieved evidence IDs.

`DirectorPlan`: `{schema_version: "2.0", style_id: "gufeng", scenes: [...]}`.
Each scene: `{scene_id, segment_id, environment, objects, beats}`.
Each object: `{id, asset_id, x, y, scale, facing, label, parameters}`. Positions are
normalized 1280x720 stage coordinates; (x,y) is the object's bottom-center anchor.
Objects have stable IDs, scale defaults to 1 and facing to 1; label is at most 10 chars.
Parameters are trusted per-resource data, never markup, code, or file paths.

Each beat: `{id, anchor: {quote, occurrence: 1, edge: "start"}, visible_ids,
focus_id, keywords, actions, camera, sfx}`. The quote must match the scene segment's
original narration. Edge is start/end. At most 3 visible foreground object groups;
focus_id is one of them. Keywords are 0–2 strings of at most 10 characters each.
The next beat replaces the visible list and keywords; future information is hidden.
Camera: `{x: 0.5, y: 0.5, zoom: 1}` (normalized focus, zoom 1–1.25).

An action is `{target_id, kind, to_x?, to_y?, scale?, path?}`. Path points are `{x,y}`.
Kinds: enter, exit, move, walk, ride, open, close, unroll, handover, stamp, draw,
emphasize. Each resource card lists its supported kinds. Actions begin at the
observed speech `anchor_time` and end at the beat's end; the earlier first-beat
background visibility does not start an action. The action window must be positive
and at least one source-video frame long, otherwise compilation fails explicitly.
The renderer uses appropriate within-window timing for opening and reveals;
a stamp's actual contact remains at `anchor_time`, matching its impact sound.
An sfx is null or `{asset_id, align: "onset"|"peak", gain_db: 0}`; gain_db is an
adjustment to the catalog's calibrated gain. Aim for 18–20 cues in a typical short
film, with final validation at 12–18 triggers/minute. SFX aligns to the observed
speech anchor, which may be later than the first visual beat's start.

## Resource catalog

`assets/history/animation_resources.json` contains `{schema_version: "2.0",
environments: [...], visual_assets: [...], sfx_assets: [...]}`.
Environment IDs: mountains, road, desert, city_gate, interior, map.
Visual IDs: actor.person, actor.envoy, actor.horse, actor.caravan, prop.gate,
prop.document, prop.flag, prop.scroll, prop.seal, info.map, info.timeline,
info.portrait. Each includes id/kind/description/actions/parameters/example/license.
Map parameters use the existing validated locations/routes data contract, with
only the current two endpoint locations. Timeline parameters use one current
year/date_label/label. Portrait is a schematic person symbol, not a fabricated image.
SFX IDs: sfx.footstep, sfx.hoof, sfx.gate, sfx.paper, sfx.stamp, sfx.wind,
sfx.draw, sfx.tap, sfx.drum, sfx.chime. Each includes path, duration, onset,
peak, default_gain_db, sha256, license, description; paths are project-relative.

## Alignment and compiled render data

`MiniMaxTTS.synthesize_aligned(text, output)` returns `{audio_path, alignment_path,
words: [{text, char_start, char_end, start, end}], provider, trace_id}`. Positions
are original Unicode character offsets, times seconds in untrimmed provider audio.
Missing reliable word timestamps is an explicit error, not estimated timing.

`compile_scene(scene, segment, words, speech, resources, sources, geography=None,
fps=30, transition=.30, narration_gap=.08)` returns a resolved dictionary.
Speech is FFmpeg's `{trim_start, duration, ...}`. Scene time is provider time minus
trim_start plus transition/2. Scene duration is ceil((speech.duration+transition+
narration_gap)*fps)/fps. Resolved output:

```
{protocol:"history-director-v2", scene_id, segment_id, title, narration, duration,
 fps, environment, objects, sources, captions:[{text,start,end}],
 beats:[{id,start,end,anchor_time,visible_ids,focus_id,keywords,camera,
         actions:[{target_id,kind,start,end,from:{x,y,scale},to:{x,y,scale},path?}],
         sfx:null|{asset_id,align,gain_db}}], checks:{...}}
```

Captions use observed words, at most 24 characters, at most two lines. Every anchor
must resolve; no semantic beat gap longer than 4 seconds of final 1.15x playback.
Tiny background drift does not count as semantic action. A scene's first visual
beat begins at 0 to establish the background while its actions and sound remain
anchored to actual speech. Retain `anchor_time` alongside `start` on resolved
beats; compiled `actions[].start` equals that anchor, including on the first beat.
An explicit `enter` action does not expose its target before that action starts;
ordinary background objects may already be visible. Any optional stamp preparation
must keep actual paper contact at the same anchor used by the sound mixer.

Remotion props: `{scene, metadata, fonts, sources, director: <resolved scene>}`.
Legacy props without director continue through the old renderer. Metadata mode
and dimensions remain compatible. All frame evaluation is pure and seekable.

## Module ownership / integration

`workflows.history_director`: async generate_script(request, research, gateway),
generate_director(script, research, resources, gateway),
repair_director(script, research, resources, prior_plan, errors, gateway).
`harness.history_director`: Pydantic HistoryScript/DirectorPlan;
validate_director(plan, script, resources, research); compile_scene(...) above;
validate_film_timeline(resolved_scenes, playback_speed, transition) returns checks
and raises on violated contracts. Functions accept Pydantic objects or dictionaries.
Model format/contract repair is limited to one call per production run by the caller.

`renderers.history_sound.mix_history_audio(ffmpeg, joined, final, events, resources,
bgm_path, bgm_volume, output_dir)` returns a JSON-serializable report. Events are
`{cue_id,asset_id,at,align,gain_db}` in final film seconds. It mixes after the single
1.15x voice/video conversion; SFX assets and BGM retain normal pitch and tempo.
Negative playback starts trim the effect's leading samples, rather than shifting
the intended peak. Effects may cross scene boundaries.

Root owns orchestration, frozen-run audit, Python rendering integration, acceptance
CLI and documentation. No agent launches live production during development.
