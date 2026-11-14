import React from 'react';
import {Composition, staticFile} from 'remotion';
import type {CalculateMetadataFunction} from 'remotion';
import {HistoryScene} from './HistoryScene';
import {DirectorScene} from './DirectorScene';
import {validateDirector} from './directorData';
import {validateProps} from './data';
import type {HistoryProps} from './types';

const defaultProps: HistoryProps = {
  scene: {scene_id: 'studio', title: '历史资料', narration: '', duration: 8,
    components: [{id: 'history.timeline', parameters: {events: [{year: 1, label: '资料节点'}]}}]},
  metadata: {width: 1280, height: 720, fps: 30},
};

const calculateMetadata: CalculateMetadataFunction<HistoryProps> = async ({props, abortSignal}) => {
  if (props.director) validateDirector(props.director); else validateProps(props);
  const width = Number(props.metadata.width ?? 1280);
  const height = Number(props.metadata.height ?? 720);
  const fps = Number(props.metadata.fps ?? 30);
  if (![width, height, fps].every(Number.isFinite) || width < 320 || height < 320 || fps <= 0) throw new Error('Invalid render dimensions or fps.');
  let land = props._land;
  if (props.director?.objects.some((o) => o.asset_id === 'info.map') || (!props.director && props.scene.components[0].id === 'history.map')) {
    const response = await fetch(staticFile('data/land.geojson'), {signal: abortSignal});
    if (!response.ok) throw new Error('Natural Earth land data is missing: public/data/land.geojson');
    land = await response.json();
  }
  let portrait = props._portrait;
  const component = props.director ? undefined : props.scene.components[0];
  if (component?.id === 'history.person' && component.parameters.portrait_asset) {
    const response = await fetch(staticFile('portraits/SOURCES.json'), {signal: abortSignal});
    if (!response.ok) throw new Error('Portrait asset provenance is missing.');
    const manifest = await response.json();
    const asset = manifest.assets?.find((a: {path: string}) => a.path === component.parameters.portrait_asset);
    if (!asset?.caption || !asset?.license || !asset?.source_url) throw new Error('Portrait asset must have a licensed source and historically accurate caption.');
    portrait = {caption: asset.caption, source_url: asset.source_url};
  }
  return {width, height, fps, durationInFrames: Math.max(1, Math.ceil((props.director?.duration ?? props.scene.duration) * fps - 1e-8)), props: {...props, _land: land, _portrait: portrait}, defaultCodec: 'h264', defaultPixelFormat: 'yuv420p'};
};

const SceneRouter: React.FC<HistoryProps> = (props) => props.director ? <DirectorScene {...props}/> : <HistoryScene {...props}/>;
export const Root: React.FC = () => <Composition id="KnowledgeScene" component={SceneRouter} defaultProps={defaultProps} calculateMetadata={calculateMetadata} width={1280} height={720} fps={30} durationInFrames={240}/>;
