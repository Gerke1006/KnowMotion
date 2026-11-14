# History Remotion project

`KnowledgeScene` is the silent, frame-deterministic scene renderer used by the project's Python Agent. Actual MiniMax narration, scene transitions, playback speed and BGM are composed by FFmpeg outside React.

```powershell
npm ci
npm run typecheck
npm test
npm run studio
```

The Python adapter supplies `{scene, metadata, fonts, sources}`. `calculateMetadata` derives dimensions, frame rate and duration from those props. A scene contains one `history.map`, `history.timeline`, or `history.person` component. History model output is data; the project never executes model-generated JavaScript.

Director v2 supplies the additional `director` prop defined in `docs/HISTORY_DIRECTOR_PROTOCOL.md` at the repository root. `DirectorScene` executes its compiled, observed-speech timeline; the legacy component path remains available when this prop is absent. The twelve trusted SVG resources form scenes with independently moving travelers, seated riders, caravans, hinged gates, handed-over documents, scrolls and stamps. Foreground, middle ground and distant landscape respond differently to the camera. All figures and scenery are explicitly schematic, not reconstructions of a particular person's likeness or period dress.

`evaluateDirector()` is the shared pure function for rendering and machine inspection. It applies cumulative transforms and articulated state, hides future objects, removes previous groups, and reads exact caption intervals rather than estimating speech from text length. The audit inspects every frame, visible groups, fixed text geometry, caption obstruction, supported action consumption and periods without a semantic state change. `directorText.ts` supplies every map, timeline and portrait text node to both SVG rendering and the audit, including precise SVG `textLength`, placement, character limits and visibility. The audit checks both asset and output-frame bounds, plus overlaps with other visible text. Background drift and subtitle paging do not count as semantic movement. Gaps are divided by `metadata.playback_speed` (default 1.15); a gap over four final-video seconds fails. Its object bounds remain conservative art envelopes; rendered stills are for visual quality review, not a substitute for these automatic text checks.

```powershell
npx tsx tools/check-director.ts --props path/to/scene.remotion.json --output path/to/director-audit.json
```

The JSON includes `passed`, `issues`, `unconsumed_actions`, summary metrics and frame-by-frame states. An issue makes this command fail. Only technical fixtures may be handwritten; production narration, objects and cues must come from the configured Agent pipeline.

- **Map:** local Natural Earth physical land polygons, plotted longitude/latitude, labeled nodes, progressive schematic paths and a moving geographic focus. No present-day national borders are represented as ancient boundaries. Coordinates and links are explanatory approximations, with their limits labeled on screen.
- **Timeline:** numeric civil years drive spatial positions; negative years are BCE and year zero is rejected. Optional `date_label` retains an approximate period or source-qualified date without presenting its numeric layout anchor as an exact fact. Long descriptions stay in a focused annotation instead of overlapping date labels.
- **People:** a typographic archival medallion is explicitly labeled symbolic, not a reconstructed historical likeness. Approved local portrait files may be placed under `public/portraits/`; source/license metadata belongs in the asset catalog. No remote portrait fetching or arbitrary path access is allowed.

Body fonts use Times New Roman followed by SimSun; subtitles use Times New Roman followed by Microsoft YaHei Bold, with a white fill and navy outline. System fonts are used without copying proprietary font files. Font readiness is awaited before frame capture. Narration paging uses `scene.audio.narration_duration` and `narration_offset`; captions disappear during the silent transition handles.

The warm archival-paper palette, restrained collage layering, annotation strokes and continuous geometric motion refer to [motion-showreel](https://github.com/ConardLi/garden-skills/blob/main/skills/motion-showreel/README.zh-CN.md) and its [editorial-collage grammar](https://github.com/ConardLi/garden-skills/blob/main/skills/motion-showreel/references/styles/editorial-collage.md). These are independently implemented components, not copied artwork or the upstream production workflow.

See `public/data/SOURCES.json` for the physical geography asset provenance. Remotion APIs follow the official [Composition](https://www.remotion.dev/docs/composition) and [calculateMetadata](https://www.remotion.dev/docs/calculate-metadata) documentation. All Remotion packages are pinned together in the lockfile.

Unit fixtures and Studio defaults are only development aids. End-to-end acceptance must use `python scripts/verify_live.py` from the repository root so the configured project model and real narration pipeline generate the content. A fixture render cannot substitute for that live acceptance.
