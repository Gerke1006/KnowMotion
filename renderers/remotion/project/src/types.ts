import type {GeoPermissibleObjects} from 'd3-geo';
import type {DirectorSceneData} from './directorTypes';

export type Source = {id?: string; title?: string; url?: string; provider?: string};
export type Location = {id: string; name: string; lon: number; lat: number; year?: number | string; description?: string; source_ids?: string[]};
export type Route = {id?: string; from: string; to: string; label?: string; kind?: 'schematic'; source_ids?: string[]};
export type MapParams = {title?: string; locations: Location[]; routes?: Route[]; viewport?: {west: number; east: number; south: number; north: number}; note?: string; source_ids?: string[]};
export type TimelineEvent = {year: number; date_label?: string; label: string; detail?: string; source_ids?: string[]};
export type TimelineParams = {title?: string; events: TimelineEvent[]; range?: [number, number]; note?: string; source_ids?: string[]};
export type PersonParams = {name: string; role: string; years?: string; facts: string[]; portrait_asset?: string; related?: {name: string; relation: string}[]; source_ids?: string[]};
export type HistoryComponent =
  | {id: 'history.map'; parameters: MapParams}
  | {id: 'history.timeline'; parameters: TimelineParams}
  | {id: 'history.person'; parameters: PersonParams};
export type Fonts = {chinese?: string; english?: string; subtitle?: string; subtitle_weight?: string; subtitle_color?: string; outline_color?: string; outline_width?: number; background_opacity?: number};
export type Scene = {
  scene_id: string; title?: string; narration?: string; duration: number; components: HistoryComponent[];
  audio?: {narration_duration?: number; narration_offset?: number};
  extensions?: {historical_sources?: Source[]; historical_period?: string; [key: string]: unknown};
};
export type HistoryProps = {
  director?: DirectorSceneData;
  scene: Scene;
  metadata: {width?: number; height?: number; fps?: number; topic?: string; title?: string; [key: string]: unknown};
  fonts?: Fonts;
  sources?: Source[];
  _land?: GeoPermissibleObjects;
  _portrait?: {caption: string; source_url?: string};
};
