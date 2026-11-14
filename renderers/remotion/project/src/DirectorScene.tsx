import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import type {HistoryProps} from './types';
import {directorLayout, evaluateDirector, textWidth} from './directorData';
import {HistoryAsset, INK} from './HistoryAssets';
import {Scenery} from './Scenery';
import {HistoryCaption, HistoryTypography, historyFontStack} from './HistoryTypography';

export const DirectorScene: React.FC<HistoryProps> = (props) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const director = props.director!;
  const state = evaluateDirector(director, frame / fps);
  const layout=directorLayout(width,height);
  const {portrait,stageHeight,stageTop}=layout;
  // Portrait keeps the entire narrative stage, rather than cropping off actors and geography.
  const zoom = state.camera.zoom;
  const world = `translate(640 360) scale(${zoom}) translate(${-state.camera.x*1280} ${-state.camera.y*720})`;
  const sources = director.sources ?? props.sources ?? [];
  return <AbsoluteFill style={{background: INK.paper, fontFamily: historyFontStack(props.fonts?.english, props.fonts?.chinese), fontWeight:900, fontSynthesis:'none', overflow:'hidden'}}>
    <HistoryTypography/>
    <svg viewBox="0 0 1280 720" width={width} height={stageHeight} style={{position:'absolute',top:stageTop,overflow:'visible'}}>
      <Scenery environment={director.environment} camera={state.camera}/>
      <g transform={world}>
        {[...state.objects].sort((a,b) => (a.object.asset_id==='prop.gate'?-1:0)-(b.object.asset_id==='prop.gate'?-1:0) || a.y-b.y).map((object) => <g key={object.object.id} opacity={object.opacity} transform={`translate(${object.x*1280} ${object.y*720}) scale(${object.scale*(1+object.emphasis)})`}>
          <g transform={object.object.asset_id.startsWith('actor.') ? `scale(${object.facing} 1)` : undefined}><HistoryAsset state={object} land={props._land}/></g>
          {object.object.label && <text x="0" y="27" textAnchor="middle" fontSize="22" textLength={textWidth(object.object.label,22)} lengthAdjust="spacingAndGlyphs" fill={INK.dark} stroke={INK.paper} strokeWidth="5" paintOrder="stroke">{object.object.label}</text>}
        </g>)}
      </g>
    </svg>
    <div style={{position:'absolute',top:portrait ? 38 : 27,left:'5.4%',right:'5.4%',display:'flex',justifyContent:'space-between',fontSize:Math.max(12,width*.011),color:director.environment==='interior'&&!portrait?INK.light:INK.muted,letterSpacing:2}}><span>历史札记</span><span>历史情境示意</span></div>
    <div style={{position:'absolute',bottom:portrait?24:4,left:'7.5%',right:'7.5%',fontSize:portrait?Math.max(12,width*.019):Math.max(11,width*.0105),lineHeight:1.2,color:INK.muted,textAlign:'center',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>
      {sources.slice(0,2).map((s) => (s.title ?? s.provider ?? '历史资料').slice(0,portrait?25:52)).join(' / ')}
    </div>
    <HistoryCaption text={state.caption} width={width} height={height} fonts={props.fonts}/>
  </AbsoluteFill>;
};
