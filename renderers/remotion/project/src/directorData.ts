import {clamp, ease} from './data';
import type {ActionKind, AssetId, Camera, DirectorAction, DirectorObject, DirectorSceneData, ObjectFrame} from './directorTypes';
import {assetText,assetTextLengths,textWidth} from './directorText';
export {textWidth} from './directorText';

export const ASSET_SIZES: Record<AssetId, [number, number]> = {
  'actor.person': [110, 210], 'actor.envoy': [110, 220], 'actor.horse': [260, 220], 'actor.caravan': [340, 230],
  'prop.gate': [440, 340], 'prop.document': [150, 145], 'prop.flag': [140, 240], 'prop.scroll': [360, 200],
  'prop.seal': [140, 200], 'info.map': [760, 370], 'info.timeline': [700, 200], 'info.portrait': [220, 280],
};
export const ACTION_KINDS: ActionKind[] = ['enter', 'exit', 'move', 'walk', 'ride', 'open', 'close', 'unroll', 'handover', 'stamp', 'draw', 'emphasize'];
const common: ActionKind[] = ['enter','exit','move','emphasize'];
export const ASSET_ACTIONS: Record<AssetId, ActionKind[]> = {
  'actor.person': [...common,'walk','handover'], 'actor.envoy': [...common,'walk','handover'],
  'actor.horse': [...common,'ride','walk'], 'actor.caravan': [...common,'ride','walk'],
  'prop.gate': [...common,'open','close'], 'prop.document': [...common,'handover','open'],
  'prop.flag': [...common,'draw'], 'prop.scroll': [...common,'unroll','open','close'],
  'prop.seal': [...common,'stamp'], 'info.map': [...common,'draw'], 'info.timeline': [...common,'draw'], 'info.portrait': common,
};
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const rectOverlap = (a: Box, b: Box) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
export type Box = {x: number; y: number; width: number; height: number};
export function directorLayout(width=1280,height=720) {
  const portrait=height>width*1.15, stageScale=width/1280, stageHeight=720*stageScale;
  return {width,height,portrait,stageScale,stageHeight,stageTop:portrait?Math.max(80,(height-stageHeight)*.34):(height-stageHeight)/2,
    keywordSize:portrait?Math.max(26,width*.047):Math.max(25,width*.034), keywordY:portrait?102:68,
    captionSize:portrait?Math.max(24,width*.042):Math.max(24,width*.026), captionBottom:portrait?66:23};
}
export function captionLayout(text:string,width=1280,height=720) {
  const layout=directorLayout(width,height), available=width*.85-28;
  const lines:string[]=[];
  for(const paragraph of text.split('\n')) {
    let current='';
    for(const char of paragraph) {if(current && textWidth(current+char,layout.captionSize)>available){lines.push(current);current='';}current+=char;}
    lines.push(current);
  }
  const boxHeight=Math.max(layout.portrait?78:65,lines.length*layout.captionSize*1.35+14);
  return {text:lines.join('\n'),box:{x:width*.075,y:height-layout.captionBottom-boxHeight,width:width*.85,height:boxHeight}};
}
export function keywordLayout(keywords:string[],width=1280,height=720) {
  const layout=directorLayout(width,height),gap=layout.portrait?15:35;
  const widths=keywords.map((s)=>textWidth(s,layout.keywordSize)+20);
  const total=widths.reduce((a,b)=>a+b,0)+Math.max(0,widths.length-1)*gap;
  let x=(width-total)/2;
  return keywords.map((text,i)=>{const box={x,y:layout.keywordY,width:widths[i],height:layout.keywordSize*1.25+9};x+=widths[i]+gap;return{text,box};});
}

export function validateDirector(d: DirectorSceneData): void {
  if (d.protocol !== 'history-director-v2' || !finite(d.duration) || d.duration <= 0 || !finite(d.fps) || d.fps <= 0) throw new Error('Invalid history director protocol or duration.');
  if (!['mountains', 'road', 'desert', 'city_gate', 'interior', 'map'].includes(d.environment)) throw new Error('Unsupported history environment.');
  if (!Array.isArray(d.objects) || !Array.isArray(d.beats) || !d.beats.length) throw new Error('Director needs objects and timed beats.');
  const ids = new Set<string>();
  for (const o of d.objects) {
    if (!o.id || ids.has(o.id) || !ASSET_SIZES[o.asset_id]) throw new Error(`Unsupported or duplicate director object: ${o.id}/${o.asset_id}`);
    ids.add(o.id);
    if (![o.x, o.y, o.scale ?? 1].every(finite) || (o.scale ?? 1) <= 0 || (o.label?.length ?? 0) > 10) throw new Error(`Invalid object position or label: ${o.id}`);
  }
  const beatIds = new Set<string>();
  let lastEnd = 0;
  for (const b of d.beats) {
    if (!b.id || beatIds.has(b.id) || !finite(b.start) || !finite(b.end) || b.start < lastEnd - .0001 || b.end <= b.start || b.end > d.duration + .001) throw new Error(`Invalid beat timing: ${b.id}`);
    beatIds.add(b.id); lastEnd = b.end;
    if (!Array.isArray(b.visible_ids) || b.visible_ids.length > 3 || new Set(b.visible_ids).size !== b.visible_ids.length || b.visible_ids.some((id) => !ids.has(id)) || !b.visible_ids.includes(b.focus_id)) throw new Error(`Invalid visible groups: ${b.id}`);
    if (!Array.isArray(b.keywords) || b.keywords.length > 2 || b.keywords.some((s) => [...s].length > 10)) throw new Error(`Keyword density exceeded: ${b.id}`);
    if (!b.camera || ![b.camera.x, b.camera.y, b.camera.zoom].every(finite) || b.camera.zoom < 1 || b.camera.zoom > 1.25) throw new Error(`Invalid camera: ${b.id}`);
    for (const a of b.actions) {
      const asset = d.objects.find((o) => o.id === a.target_id);
      if (!asset || !b.visible_ids.includes(a.target_id) || !ASSET_ACTIONS[asset.asset_id].includes(a.kind)) throw new Error(`Unsupported action target/kind: ${a.target_id}/${a.kind}`);
      if (![a.start, a.end, a.from?.x, a.from?.y, a.from?.scale, a.to?.x, a.to?.y, a.to?.scale].every(finite) || a.start < b.start - .001 || a.end > b.end + .001 || a.end <= a.start) throw new Error(`Invalid action timing or transform: ${b.id}`);
      if (a.path && (a.path.length < 2 || a.path.some((p) => !finite(p.x) || !finite(p.y)))) throw new Error(`Invalid action path: ${b.id}`);
    }
  }
  for (const c of d.captions ?? []) if (!finite(c.start) || !finite(c.end) || c.start < 0 || c.end <= c.start || c.end > d.duration + .001 || [...c.text].filter((v) => v !== '\n').length > 24) throw new Error('Invalid observed caption.');
}

/** Distance-based traversal avoids acceleration at every intermediate path vertex. */
export function pathPoint(path: {x: number; y: number}[], progress: number): {x: number; y: number} {
  const lengths = path.slice(1).map((point, i) => Math.hypot(point.x - path[i].x, (point.y - path[i].y) * 720 / 1280));
  let distance = clamp(progress) * lengths.reduce((a, b) => a + b, 0);
  for (let i = 0; i < lengths.length; i++) {
    if (distance <= lengths[i] || i === lengths.length - 1) {const p = lengths[i] ? distance / lengths[i] : 1; return {x: lerp(path[i].x, path[i + 1].x, p), y: lerp(path[i].y, path[i + 1].y, p)};}
    distance -= lengths[i];
  }
  return path.at(-1)!;
}

function applyAction(state: ObjectFrame, a: DirectorAction, seconds: number, anchorTime=a.start): void {
  if (seconds < a.start) {
    // An explicit entrance is a visibility boundary, even while the opening beat supplies scenery.
    if (a.kind === 'enter') state.opacity = 0;
    return;
  }
  const p = clamp((seconds - a.start) / (a.end - a.start));
  const active = seconds < a.end;
  const fast = ease((seconds - a.start) / Math.min(1.05, (a.end - a.start) * .7));
  const moving = ['move', 'walk', 'ride', 'handover'].includes(a.kind);
  const k = moving ? ease(p) : fast;
  const point = a.path?.length ? pathPoint(a.path, k) : {x: lerp(a.from.x, a.to.x, k), y: lerp(a.from.y, a.to.y, k)};
  state.x = point.x; state.y = point.y; state.scale = lerp(a.from.scale, a.to.scale, k);
  if (moving && Math.abs(a.to.x - a.from.x) > .001) state.facing = a.to.x >= a.from.x ? 1 : -1;
  if (a.kind === 'open') {state.gateOpen = fast; if (state.object.asset_id === 'prop.scroll') state.scrollOpen = fast;}
  if (a.kind === 'close') {state.gateOpen = 1 - fast; if (state.object.asset_id === 'prop.scroll') state.scrollOpen = 1 - fast;}
  if (a.kind === 'unroll') state.scrollOpen = fast;
  if (a.kind === 'draw') state.draw = ease(p);
  // The seal contacts paper on the same observed speech anchor used by the SFX mixer.
  if (a.kind === 'stamp') state.stamp = clamp(seconds-anchorTime,-.18,.24);
  if (a.kind === 'handover') state.handover = fast;
  if (active) {
    state.action = a.kind; state.actionProgress = p; state.motionTime = seconds - a.start;
    if (a.kind === 'enter') state.opacity *= ease((seconds - a.start) / Math.min(.5, a.end - a.start));
    if (a.kind === 'exit') state.opacity *= 1 - ease((seconds - Math.max(a.start, a.end - .45)) / Math.min(.45, a.end - a.start));
    if (a.kind === 'emphasize') state.emphasis = Math.sin(Math.PI * clamp((seconds - a.start) / .5)) * .09;
  } else if (a.kind === 'exit') state.opacity = 0;
}

/** The exact state consumed by the visual renderer and its QA exporter. No timers or previous-frame state. */
export function evaluateDirector(d: DirectorSceneData, seconds: number) {
  const beatIndex = d.beats.findIndex((b) => seconds >= b.start && seconds < b.end);
  const beat = d.beats[beatIndex];
  const previous = beatIndex > 0 ? d.beats[beatIndex - 1] : undefined;
  const oldCamera: Camera = previous?.camera ?? {x: .5, y: .5, zoom: 1};
  const mix = beat ? ease((seconds - beat.start) / Math.min(.8, (beat.end - beat.start) * .35)) : 0;
  const camera = beat ? {x: lerp(oldCamera.x, beat.camera.x, mix), y: lerp(oldCamera.y, beat.camera.y, mix), zoom: lerp(oldCamera.zoom, beat.camera.zoom, mix)} : oldCamera;
  const objects: ObjectFrame[] = [];
  const consumed: string[] = [];
  if (beat) for (const id of beat.visible_ids) {
    const object = d.objects.find((o) => o.id === id)!;
    const state: ObjectFrame = {object, x: object.x, y: object.y, scale: object.scale ?? 1, facing: object.facing ?? 1, opacity: 1,
      actionProgress: 0, motionTime: 0, gateOpen: 0, scrollOpen: 0, draw: 0, stamp: -.18, handover: 0, emphasis: 0, focus: id === beat.focus_id};
    // Prior transforms and articulated states persist; prior visibility never leaks into this beat.
    for (const prior of d.beats.slice(0, beatIndex)) for (const a of prior.actions) if (a.target_id === id) {
      applyAction(state, a, prior.end + .001,prior.anchor_time??prior.start); state.opacity = 1; state.action = undefined; state.emphasis = 0;
    }
    if (!previous?.visible_ids.includes(id) && !beat.actions.some((a)=>a.target_id===id&&a.kind==='stamp')) state.opacity *= ease((seconds - beat.start) / .22);
    for (const [i, action] of beat.actions.entries()) if (action.target_id === id) {
      applyAction(state, action, seconds,beat.anchor_time??beat.start);
      if (seconds >= action.start) consumed.push(`${beat.id}:${i}`);
    }
    objects.push(state);
  }
  const caption = d.captions.find((c) => seconds >= c.start && seconds < c.end)?.text ?? '';
  const keywords = beat && seconds >= (beat.anchor_time ?? beat.start) ? beat.keywords : [];
  return {beat, beatIndex, objects, camera, caption, keywords, consumed};
}

export function objectBox(state: ObjectFrame, camera: Camera): Box {
  const [w, h] = ASSET_SIZES[state.object.asset_id];
  const scale = state.scale * (1 + state.emphasis) * camera.zoom;
  const x = 640 + (state.x * 1280 - camera.x * 1280) * camera.zoom;
  const y = 360 + (state.y * 720 - camera.y * 720) * camera.zoom;
  return {x: x - w * scale / 2, y: y - h * scale, width: w * scale, height: h * scale};
}

export function auditDirector(d: DirectorSceneData, fps = d.fps,width=1280,height=720,playbackSpeed=1.15) {
  validateDirector(d);
  if(!Number.isFinite(playbackSpeed)||playbackSpeed<=0)throw new Error('Invalid final playback speed.');
  const consumed = new Set<string>();
  const frames: {frame: number; beat: string | null; groups: string[]; keywords: string[]; caption: string; semantic_signature:string; text_boxes: {kind:string;text:string;box:Box}[]; boxes: {id: string; box: Box; captionOverlap: boolean; outsideStage: boolean}[]}[] = [];
  const issues: {frame: number; kind: string; object_id?: string;text?:string;limit?:number;seconds?:number}[] = [];
  const layout=directorLayout(width,height);
  let lastSemantic='',unchangedFrames=0,maxUnchangedFrames=0;
  for (let frame = 0; frame < Math.ceil(d.duration * fps); frame++) {
    const state = evaluateDirector(d, frame / fps);
    state.consumed.forEach((id) => consumed.add(id));
    const visible = state.objects.filter((o) => o.opacity > .02);
    const quantize=(v:number)=>Math.round(v*100)/100;
    const semanticSignature=JSON.stringify({objects:visible.map((o)=>({id:o.object.id,x:quantize(o.x),y:quantize(o.y),scale:quantize(o.scale),gate:quantize(o.gateOpen),scroll:quantize(o.scrollOpen),draw:quantize(o.draw),stamp:quantize(o.stamp),handover:quantize(o.handover),emphasis:quantize(o.emphasis),gait:o.action==='walk'||o.action==='ride'?Math.floor(o.motionTime*6)%12:0})),keywords:state.keywords});
    unchangedFrames=semanticSignature===lastSemantic?unchangedFrames+1:1; maxUnchangedFrames=Math.max(maxUnchangedFrames,unchangedFrames);lastSemantic=semanticSignature;
    const captionBox=captionLayout(state.caption,width,height).box;
    const textBoxes=keywordLayout(state.keywords,width,height).map((k)=>({kind:'keyword',...k}));
    if(state.caption)textBoxes.push({kind:'caption',text:state.caption,box:captionBox});
    const boxes = visible.map((o) => {
      const logical = objectBox(o, state.camera);
      const box={x:logical.x*layout.stageScale,y:logical.y*layout.stageScale+layout.stageTop,width:logical.width*layout.stageScale,height:logical.height*layout.stageScale};
      const captionOverlap = !!state.caption && rectOverlap(box, captionBox) > 0;
      const outsideStage = box.x < -1 || box.x + box.width > width+1 || box.y < -1 || box.y + box.height > height+1;
      if(o.object.label){const scale=o.scale*(1+o.emphasis)*state.camera.zoom*layout.stageScale;const w=textWidth(o.object.label,22)*scale; textBoxes.push({kind:'object_label',text:o.object.label,box:{x:box.x+box.width/2-w/2,y:box.y+box.height+6*scale,width:w,height:25*scale}});}
      const scale=o.scale*(1+o.emphasis)*state.camera.zoom*layout.stageScale;
      const origin={x:box.x+box.width/2,y:box.y+box.height};
      for(const text of assetText(o).filter(t=>t.opacity>.02)){
        const local=text.box;
        const textBox={x:origin.x+local.x*scale,y:origin.y+local.y*scale,width:local.width*scale,height:local.height*scale};
        textBoxes.push({kind:text.kind,text:text.text,box:textBox});
        const [assetW,assetH]=ASSET_SIZES[o.object.asset_id];
        if(local.x < -assetW/2-.01 || local.x+local.width>assetW/2+.01 || local.y < -assetH-.01 || local.y+local.height> .01)issues.push({frame,kind:'text_outside_asset',object_id:o.object.id,text:text.text});
      }
      for(const t of assetTextLengths(o))if([...t.text].length>t.limit)issues.push({frame,kind:'text_character_limit',object_id:o.object.id,text:t.text,limit:t.limit});
      // Large scenery may intentionally bleed. Information objects and labels must remain safe.
      if (o.object.asset_id.startsWith('info.') && outsideStage) issues.push({frame, kind: 'information_outside_stage', object_id: o.object.id});
      if (captionOverlap) issues.push({frame, kind: 'object_caption_overlap', object_id: o.object.id});
      return {id: o.object.id, box, captionOverlap, outsideStage};
    });
    for(let i=0;i<textBoxes.length;i++){
      const a=textBoxes[i]; if(a.box.x<0||a.box.x+a.box.width>width||a.box.y<0||a.box.y+a.box.height>height)issues.push({frame,kind:'text_outside_frame'});
      for(const b of textBoxes.slice(i+1))if(rectOverlap(a.box,b.box)>0)issues.push({frame,kind:'text_overlap'});
    }
    frames.push({frame, beat: state.beat?.id ?? null, groups: visible.map((o) => o.object.id), keywords: state.keywords, caption: state.caption,semantic_signature:semanticSignature,text_boxes:textBoxes,boxes});
  }
  const expected = d.beats.flatMap((b) => b.actions.map((_, i) => `${b.id}:${i}`));
  const finalSemanticGap=maxUnchangedFrames/fps/playbackSpeed;
  if(finalSemanticGap>4+1/fps/playbackSpeed)issues.push({frame:-1,kind:'semantic_gap',seconds:finalSemanticGap});
  const unconsumed=expected.filter((id)=>!consumed.has(id));
  return {passed:issues.length===0&&unconsumed.length===0,protocol: d.protocol, scene_id: d.scene_id, fps,width,height, playback_speed:playbackSpeed,frame_count: frames.length,
    maximum_visible_groups: Math.max(...frames.map((f) => f.groups.length)), maximum_keyword_groups: Math.max(...frames.map((f) => f.keywords.length)), maximum_unchanged_semantic_seconds:finalSemanticGap,maximum_unchanged_semantic_source_seconds:maxUnchangedFrames/fps,
    consumed_actions: [...consumed], unconsumed_actions: unconsumed, issues, frames};
}
