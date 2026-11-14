import React, {useEffect, useState} from 'react';
import {AbsoluteFill, cancelRender, continueRender, delayRender, useCurrentFrame, useVideoConfig} from 'remotion';
import type {HistoryProps} from './types';
import type {Camera, DirectorSceneData} from './directorTypes';
import {captionLayout, directorLayout, evaluateDirector, keywordLayout, textWidth} from './directorData';
import {HistoryAsset, INK} from './HistoryAssets';

const fontStack = (english = 'Times New Roman', chinese = 'SimSun') => `"${english}", "${chinese}", serif`;

function Scenery({environment, camera}: {environment: DirectorSceneData['environment']; camera: Camera}) {
  const layer = (depth: number) => `translate(${(0.5-camera.x)*1280*depth} ${(0.5-camera.y)*720*depth}) translate(640 360) scale(${1+(camera.zoom-1)*depth}) translate(-640 -360)`;
  const desert = environment === 'desert';
  const indoor = environment === 'interior';
  return <g>
    <defs>
      <linearGradient id="director-sky" x2="0" y2="1"><stop stopColor={indoor ? '#d6c8a8' : '#e8e7d6'}/><stop offset="1" stopColor="#f5eddc"/></linearGradient>
      <linearGradient id="director-earth" x2="0" y2="1"><stop stopColor={desert ? '#d0b98d' : '#cbd0b9'}/><stop offset="1" stopColor="#e5d9bb"/></linearGradient>
      <pattern id="director-grain" width="63" height="71" patternUnits="userSpaceOnUse"><path d="M6 4h1M37 51h1M54 19h2M12 61h1" stroke="#6e6c59" strokeWidth="1" opacity=".12"/></pattern>
    </defs>
    <rect x="-200" y="-120" width="1680" height="960" fill="url(#director-sky)"/>
    <g transform={layer(.2)}>
      {!indoor && <><circle cx="1025" cy="133" r="60" fill="#b5774f" opacity=".3"/><path d="M-230 425L-80 304L38 357L187 205L337 330L473 188L611 348L743 242L879 348L1087 177L1266 315L1500 233V700H-230Z" fill={desert ? '#c8b997' : '#98aaa0'} opacity=".32"/><path d="M-230 471L16 359L169 413L302 307L455 412L590 336L742 414L947 292L1118 393L1322 317L1500 433V730H-230Z" fill={desert ? '#beaa83' : '#869b8b'} opacity=".38"/></>}
      {indoor && <><path d="M-100 69H1380V473H-100Z" fill="#d7ceb8"/><path d="M105 90V450M397 90V450M882 90V450M1174 90V450M105 110H1174M105 210H1174M105 310H1174M105 410H1174" stroke="#aaa08a" strokeWidth="6"/><path d="M397 90H882V450H397Z" fill="#eae2ce"/></>}
    </g>
    <g transform={layer(.5)}>
      <path d="M-240 506Q150 376 511 461Q881 372 1500 486V850H-240Z" fill="url(#director-earth)"/>
      {!indoor && <path d="M675 424Q554 464 760 512Q871 540 1020 767H571Q650 583 558 536Q405 468 675 424Z" fill={desert ? '#e4cfa3' : '#e6dbc0'} opacity=".95"/>}
      {environment === 'city_gate' && <path d="M-180 438V343H-134V327H-101V343H-51V327H-17V343H33V327H65V343H115V327H148V343H209V438M1093 438V349H1141V333H1176V349H1226V333H1258V349H1308V333H1340V349H1410V438" fill="#aaa98f" stroke="#8e947e" strokeWidth="2" opacity=".6"/>}
      {indoor && <><path d="M-200 455H1480" stroke="#8e7b60" strokeWidth="9"/><path d="M0 720L400 456M1280 720L880 456M640 456V800M-200 560H1480M-200 660H1480" stroke="#b5a789" strokeWidth="2" opacity=".6"/></>}
    </g>
    <g transform={layer(.85)} opacity=".8">
      {indoor ? <><path d="M-70-80H85V720H-70M1195-80H1350V720H1195" fill="#665347"/><path d="M85-10Q185 61 312-10M965-10Q1097 63 1195-10" stroke="#7a4d39" fill="none" strokeWidth="40"/></> : <>
        <path d="M-80 662Q28 538 118 570L168 637L233 654V760H-80M1095 704Q1152 580 1254 594L1360 650V790H1095Z" fill="#64766a" opacity=".38"/>
        <path d="M-20 708L30 548M30 621L-8 573M27 628L67 585M1210 707L1258 559M1243 606L1211 575M1232 641L1280 604" stroke="#66776a" strokeWidth="4" fill="none"/>
      </>}
    </g>
    <rect width="1280" height="720" fill="url(#director-grain)" pointerEvents="none"/>
  </g>;
}

export const DirectorScene: React.FC<HistoryProps> = (props) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const [fontHandle] = useState(() => delayRender('Loading director fonts'));
  useEffect(() => {
    Promise.all([document.fonts.load(`30px "${props.fonts?.chinese ?? 'SimSun'}"`, '历史'), document.fonts.load(`700 30px "${props.fonts?.subtitle ?? 'Microsoft YaHei'}"`, '历史'), document.fonts.ready]).then(() => continueRender(fontHandle)).catch(cancelRender);
  }, [fontHandle, props.fonts?.chinese, props.fonts?.subtitle]);
  const director = props.director!;
  const state = evaluateDirector(director, frame / fps);
  const layout=directorLayout(width,height);
  const {portrait,stageScale,stageHeight,stageTop,keywordSize,captionSize}=layout;
  const caption=captionLayout(state.caption,width,height);
  // Portrait keeps the entire narrative stage, rather than cropping off actors and geography.
  const zoom = state.camera.zoom;
  const world = `translate(640 360) scale(${zoom}) translate(${-state.camera.x*1280} ${-state.camera.y*720})`;
  const sources = director.sources ?? props.sources ?? [];
  return <AbsoluteFill style={{background: INK.paper, fontFamily: fontStack(props.fonts?.english, props.fonts?.chinese), overflow:'hidden'}}>
    <svg viewBox="0 0 1280 720" width={width} height={stageHeight} style={{position:'absolute',top:stageTop,overflow:'visible'}}>
      <Scenery environment={director.environment} camera={state.camera}/>
      <g transform={world}>
        {[...state.objects].sort((a,b) => (a.object.asset_id==='prop.gate'?-1:0)-(b.object.asset_id==='prop.gate'?-1:0) || a.y-b.y).map((object) => <g key={object.object.id} opacity={object.opacity} transform={`translate(${object.x*1280} ${object.y*720}) scale(${object.scale*(1+object.emphasis)})`}>
          <g transform={object.object.asset_id.startsWith('actor.') ? `scale(${object.facing} 1)` : undefined}><HistoryAsset state={object} land={props._land}/></g>
          {object.object.label && <text x="0" y="27" textAnchor="middle" fontSize="22" textLength={textWidth(object.object.label,22)} lengthAdjust="spacingAndGlyphs" fill={INK.dark} stroke={INK.paper} strokeWidth="5" paintOrder="stroke">{object.object.label}</text>}
        </g>)}
      </g>
    </svg>
    <div style={{position:'absolute',top:portrait ? 38 : 27,left:'5.4%',right:'5.4%',display:'flex',justifyContent:'space-between',fontSize:Math.max(12,width*.011),color:INK.muted,letterSpacing:2}}><span>历史札记</span><span>历史情境示意</span></div>
    {!!state.keywords.length && <svg width={width} height={height} style={{position:'absolute',inset:0,pointerEvents:'none'}}>
      {keywordLayout(state.keywords,width,height).map(({text,box},i)=><g key={`${state.beat?.id}-${i}`}><rect x={box.x} y={box.y} width={box.width} height={box.height} fill={INK.light} opacity=".82"/><path d={`M${box.x} ${box.y+box.height}H${box.x+box.width}`} stroke={i===0?INK.cinnabar:INK.gold} strokeWidth={i===0?3:1}/><text x={box.x+box.width/2} y={box.y+keywordSize+2} textAnchor="middle" fontSize={keywordSize} textLength={box.width-20} lengthAdjust="spacingAndGlyphs" fill={INK.dark}>{text}</text></g>)}
    </svg>}
    <div style={{position:'absolute',bottom:portrait?24:4,left:'7.5%',right:'7.5%',fontSize:portrait?Math.max(12,width*.019):Math.max(11,width*.0105),lineHeight:1.2,color:INK.muted,textAlign:'center',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>
      {sources.slice(0,2).map((s) => (s.title ?? s.provider ?? '历史资料').slice(0,portrait?25:52)).join(' / ')}
    </div>
    {state.caption && <div style={{position:'absolute',left:caption.box.x,top:caption.box.y,width:caption.box.width,height:caption.box.height,padding:'7px 14px',boxSizing:'border-box',display:'flex',justifyContent:'center',alignItems:'center',textAlign:'center',whiteSpace:'pre',fontFamily:fontStack(props.fonts?.english,props.fonts?.subtitle??'Microsoft YaHei'),fontWeight:700,fontSize:captionSize,lineHeight:1.35,color:props.fonts?.subtitle_color??'#fff',WebkitTextStroke:`${(props.fonts?.outline_width??5)/2}px ${props.fonts?.outline_color??'#161044'}`,paintOrder:'stroke fill',background:'rgba(29,37,37,.91)',borderRadius:3}}>{caption.text}</div>}
  </AbsoluteFill>;
};
