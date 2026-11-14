import type {Source} from './types';

export type AssetId = 'actor.person' | 'actor.envoy' | 'actor.horse' | 'actor.caravan' | 'prop.gate' | 'prop.document' | 'prop.flag' | 'prop.scroll' | 'prop.seal' | 'info.map' | 'info.timeline' | 'info.portrait';
export type ActionKind = 'enter' | 'exit' | 'move' | 'walk' | 'ride' | 'open' | 'close' | 'unroll' | 'handover' | 'stamp' | 'draw' | 'emphasize';
export type Position = {x: number; y: number; scale: number};
export type DirectorObject = {id: string; asset_id: AssetId; x: number; y: number; scale?: number; facing?: number; label?: string; parameters?: Record<string, unknown>};
export type DirectorAction = {target_id: string; kind: ActionKind; start: number; end: number; from: Position; to: Position; path?: {x: number; y: number}[]};
export type Camera = {x: number; y: number; zoom: number};
export type DirectorBeat = {id: string; start: number; end: number; anchor_time?: number; visible_ids: string[]; focus_id: string; keywords: string[]; camera: Camera; actions: DirectorAction[]; sfx?: {asset_id: string; align: 'onset' | 'peak'; gain_db: number} | null};
export type DirectorSceneData = {
  protocol: 'history-director-v2'; scene_id: string; segment_id: string; title: string; narration: string;
  duration: number; fps: number; environment: 'mountains' | 'road' | 'desert' | 'city_gate' | 'interior' | 'map';
  objects: DirectorObject[]; sources: Source[]; captions: {text: string; start: number; end: number}[]; beats: DirectorBeat[];
  checks?: Record<string, unknown>;
};
export type ObjectFrame = {
  object: DirectorObject; x: number; y: number; scale: number; facing: number; opacity: number;
  action?: ActionKind; actionProgress: number; motionTime: number; gateOpen: number; scrollOpen: number;
  draw: number; stamp: number; handover: number; emphasis: number; focus: boolean;
};
