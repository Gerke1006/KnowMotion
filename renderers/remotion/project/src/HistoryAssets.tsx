import React from 'react';
import {geoPath} from 'd3-geo';
import type {GeoPermissibleObjects} from 'd3-geo';
import {clamp, ease} from './data';
import type {MapParams} from './types';
import type {ObjectFrame} from './directorTypes';
import {assetText,directorMapGeometry} from './directorText';

export const INK = {dark: '#282d2c', muted: '#747d72', cinnabar: '#a64b34', gold: '#b4935c', paper: '#efe7d4', light: '#faf4e4', jade: '#637d74', indigo: '#42585e'};
const line = {stroke: INK.dark, strokeWidth: 2, strokeLinejoin: 'round' as const, strokeLinecap: 'round' as const};

function AssetTypography({state}:{state:ObjectFrame}){
  return <>{assetText(state).map(t=><text key={t.id} x={t.x} y={t.y} textAnchor={t.anchor} fontSize={t.fontSize} textLength={t.width} lengthAdjust="spacingAndGlyphs" opacity={t.opacity}
    fill={t.kind==='timeline_date'?INK.cinnabar:t.kind.endsWith('note')||t.kind==='portrait_role'?INK.muted:INK.dark}
    stroke={t.stroke?INK.light:undefined} strokeWidth={t.stroke?5:undefined} paintOrder={t.stroke?'stroke':undefined}>{t.text}</text>)}</>;
}

function Person({state, small = false, courier = false}: {state: ObjectFrame; small?: boolean; courier?: boolean}) {
  const walking = state.action === 'walk';
  const stride = walking ? Math.sin(state.motionTime * Math.PI * 3.5) : 0;
  const bob = walking ? Math.abs(stride) * 3 : 0;
  const hand = state.action === 'handover' ? ease(state.actionProgress / .55) : state.handover;
  return <g transform={`translate(0 ${-bob}) scale(${small ? .65 : 1})`}>
    <ellipse cx="0" cy="-1" rx="36" ry="5" fill={INK.dark} opacity=".12"/>
    <g transform={`rotate(${stride * 20} -13 -66)`}><path d="M-22-83L-6-79L-9-13L-1-6Q2 0-9 0H-28L-23-20Z" fill={INK.dark}/></g>
    <g transform={`rotate(${-stride * 20} 12 -66)`}><path d="M7-83L23-81L24-17L35-8Q39-1 28 0H10L8-22Z" fill="#465452"/></g>
    <path d="M-20-159Q-34-143-33-119L-43-60Q-12-45 35-59L23-133Q18-155 8-160Z" fill={courier ? INK.cinnabar : INK.indigo} {...line}/>
    <path d="M-17-152L10-120L24-145M-34-96L30-98M-9-120L-14-59" fill="none" stroke={INK.light} opacity=".45" strokeWidth="2"/>
    <path d="M-32-100L30-102L29-93L-34-91Z" fill={INK.dark}/>
    <g transform={`rotate(${-stride * 14} -24 -142)`}><path d="M-24-145Q-39-139-44-103L-34-94Q-25-109-16-132Z" fill={courier ? '#894732' : '#374c54'} {...line}/><circle cx="-39" cy="-96" r="6" fill="#d2b28c"/></g>
    <g transform={`rotate(${-hand * 65 + stride * 11} 19 -140)`}><path d="M16-148Q34-150 38-114L30-95L18-99L20-118L7-135Z" fill={courier ? '#b66443' : '#526d71'} {...line}/><circle cx="27" cy="-96" r="6" fill="#d2b28c"/></g>
    <path d="M-9-166L-9-153L8-151L9-169Z" fill="#d2b28c"/>
    <path d="M-16-186Q-15-204 3-203Q19-199 17-183L22-176L16-173Q16-159 4-160L-10-165Z" fill="#d7b88f" {...line}/>
    <path d="M-18-183L-20-195Q-9-211 11-204L20-190L9-187L0-196L-8-182Z" fill={INK.dark}/>
    <path d="M-14-201L-17-213L2-216L8-203Z" fill={INK.dark}/>
    <path d="M-17-194L15-193" stroke={INK.gold} strokeWidth="3"/>
    {courier && <g><path d="M-32-153L24-82" stroke={INK.gold} strokeWidth="4"/><path d="M-34-135L-48-117L-39-89L-24-101Z" fill="#b69b69" {...line}/></g>}
  </g>;
}

function Horse({state, packed = false}: {state: ObjectFrame; packed?: boolean}) {
  const moving = state.action === 'ride' || state.action === 'walk';
  const phase = state.motionTime * Math.PI * (state.action === 'ride' ? 5 : 3);
  const bob = moving ? Math.sin(phase * 2) * 2 : 0;
  return <g transform={`translate(0 ${bob})`}>
    <ellipse cy="-1" rx="110" ry="7" fill={INK.dark} opacity=".12"/>
    {[-75, -52, 51, 76].map((x, i) => <g key={i} transform={`rotate(${moving ? Math.sin(phase + i * 2.1) * 22 : 0} ${x} -65)`}>
      <path d={`M${x-8}-89L${x+8}-86L${x+4}-47L${x+10}-8L${x+17}-3L${x-1}-1L${x-8}-43Z`} fill={i % 2 ? '#8a6546' : '#604c3d'} {...line}/>
    </g>)}
    <path d="M-87-107Q-121-109-121-65Q-116-86-98-84L-84-94Z" fill={INK.dark}/>
    <path d="M-90-116Q-53-137 27-120L54-155L65-179L79-172L94-151L122-139Q129-130 120-121L99-120L86-131L79-97Q65-76 38-74L-59-77Q-94-83-90-116Z" fill="#987650" {...line}/>
    <path d="M48-145L64-179L71-182L75-170L66-151L58-125" fill={INK.dark}/>
    <path d="M79-172L89-184L91-163" fill="#987650" {...line}/>
    <circle cx="100" cy="-141" r="2.6" fill={INK.dark}/>
    <path d="M114-145L107-121M88-133Q51-99-9-125" fill="none" stroke={INK.dark} strokeWidth="2"/>
    <path d="M-48-126L22-126L27-91L-49-92Z" fill={INK.cinnabar}/><path d="M-43-119H18M-39-112H17" stroke={INK.gold} strokeWidth="3"/>
    {packed ? <g><rect x="-50" y="-156" width="72" height="31" rx="8" fill="#b7a17c" {...line}/><path d="M-34-155V-126M0-155V-126" stroke={INK.dark} strokeWidth="3"/></g> : <g transform="translate(-12 -119)">
      <path d="M-15-11L23-3L12 29L25 34L24 40H1L-4 10L-25 2Z" fill={INK.dark} {...line}/>
      <path d="M-17-53L8-55L19-14L-8-6L-25-17Z" fill={INK.cinnabar} {...line}/>
      <path d="M-14-49L10-20M-22-20L15-23" stroke={INK.gold} strokeWidth="3"/>
      <path d="M7-49L21-30L40-28L42-21L17-21L1-39" fill="#ba7852" {...line}/>
      <path d="M-10-58V-49H3V-61Z" fill="#d7b88f"/>
      <path d="M-17-76Q-13-91 1-86L10-69L6-65L5-54L-9-54L-18-63Z" fill="#d7b88f" {...line}/>
      <path d="M-19-67L-19-81L-14-87L-17-96L-4-98L1-88L7-83L5-76L-5-79L-11-68Z" fill={INK.dark}/>
      <path d="M42-25L99-8" stroke={INK.dark} strokeWidth="1.5"/>
    </g>}
  </g>;
}

function Gate({open}: {open: number}) {
  return <g>
    <path d="M-215 0V-187L-151-208H148L215-184V0Z" fill="#b5b09b" {...line}/>
    <path d="M-215-74H-118M118-74H215M-215-121H-118M118-121H215M-190-186V0M190-186V0" stroke="#817f6f" strokeWidth="1.2" opacity=".7"/>
    <path d="M-110 0V-164Q0-230 110-164V0Z" fill="#343d39"/>
    <g transform={`translate(-100 0) scale(${1 - open * .88} 1)`}><path d="M0 0V-160Q38-185 100-185V0Z" fill="#7e4735" {...line}/><path d="M19-4V-163M45-4V-176M72-4V-182" stroke="#4d352c" strokeWidth="3"/><circle cx="83" cy="-83" r="5" fill={INK.gold}/></g>
    <g transform={`translate(100 0) scale(${-1 + open * .88} 1)`}><path d="M0 0V-160Q38-185 100-185V0Z" fill="#97563e" {...line}/><path d="M19-4V-163M45-4V-176M72-4V-182" stroke="#4d352c" strokeWidth="3"/><circle cx="83" cy="-83" r="5" fill={INK.gold}/></g>
    <path d="M-158-200V-266H158V-200Z" fill="#b3a58b" {...line}/><path d="M-125-210V-258M-70-210V-258M-15-210V-258M40-210V-258M95-210V-258" stroke="#6a6050" strokeWidth="5"/>
    <path d="M-212-261Q-151-270-119-311H119Q151-270 212-261L183-250H-183Z" fill={INK.indigo} {...line}/>
    <path d="M-119-311H119M-185-260H185M-166-269H166M-147-280H147" stroke="#a8b0a0" strokeWidth="2"/>
    <path d="M-217-260L-202-279M217-260L202-279M-127-310L-130-326M127-310L130-326" stroke={INK.dark} strokeWidth="5"/>
    <rect x="-39" y="-241" width="78" height="31" fill={INK.dark}/><path d="M-22-227H22M-10-235V-218M10-235V-218" stroke={INK.gold} strokeWidth="2"/>
  </g>;
}

function Scroll({open, document = false}: {open: number; document?: boolean}) {
  const width = document ? 140 : 52 + open * 296;
  const height = document ? 96 : 176;
  return <g>
    <path d={`M${-width / 2 + 5}-${height - 5}H${width / 2 + 6}V-3H${-width / 2 + 5}Z`} fill={INK.dark} opacity=".12"/>
    <rect x={-width / 2} y={-height} width={width} height={height - 8} fill={INK.light} stroke={INK.gold} strokeWidth="1.5"/>
    {document ? <g transform={`translate(0 ${-height}) scale(1 ${1-open*1.8})`}><path d={`M${-width / 2} 0L0 ${height / 2}L${width / 2} 0Z`} stroke={INK.gold} strokeWidth="1.5" fill="#e9dec2"/></g> : <>
      {[-1, 1].map((side) => <g key={side}><rect x={side * width / 2 - 7} y={-height - 8} width="14" height={height + 8} rx="5" fill="#aa8b57" {...line}/><path d={`M${side * width / 2}-${height - 5}V-16`} stroke="#e0ca94" strokeWidth="3"/></g>)}
      <g opacity={clamp((open - .3) / .4)}>{[0,1,2,3,4,5].map((column) => <path key={column} d={`M${-100 + column * 39}-143v80`} stroke={INK.muted} strokeWidth="6" strokeDasharray="5 6" opacity={column === 1 ? .6 : .35}/>)}</g>
      <rect x="85" y="-54" width="23" height="27" fill="none" stroke={INK.cinnabar} strokeWidth="3" opacity={open}/>
    </>}
    {document && <path d="M-13-60H13V-35H-13Z" fill={INK.cinnabar} opacity=".8"/>}
  </g>;
}

function Seal({progress}: {progress: number}) {
  const lift = progress < 0 ? 54*clamp(-progress/.18) : 18*ease(progress/.24);
  return <g>
    <path d="M-62-16H62V0H-62Z" fill={INK.light} stroke={INK.gold}/>
    <g opacity={progress>=0?1:0}><rect x="-27" y="-17" width="54" height="13" fill={INK.cinnabar} opacity=".72"/><path d="M-20-14H20M-12-16V-6M8-16V-6" stroke={INK.light} strokeWidth="2"/></g>
    <g transform={`translate(0 ${7-lift})`}>
      <path d="M-42-67H42V-23H-42Z" fill={INK.cinnabar} {...line}/><path d="M-29-96H29L38-68H-38Z" fill="#ab8150" {...line}/>
      <path d="M-19-101Q-20-132 3-133Q26-126 18-102Z" fill="#b79a65" {...line}/><path d="M-35-58H35M-35-32H35" stroke="#d5a570" strokeWidth="3"/>
    </g>
  </g>;
}

function MapAsset({state, land}: {state: ObjectFrame; land?: GeoPermissibleObjects}) {
  const p = state.object.parameters as unknown as MapParams;
  if (!p?.locations?.length || !land) throw new Error('Director map needs validated geographic locations and local land data.');
  const {points,projection,labels}=directorMapGeometry(p);
  const path = geoPath(projection);
  const progress = state.action === 'draw' || state.draw > 0 ? state.draw : 1;
  return <g>
    <rect x="-380" y="-370" width="760" height="370" rx="3" fill={INK.light} opacity=".68"/>
    <path d={path(land) ?? ''} fill="#cbd0b9" stroke="#8b9682" strokeWidth="1.3"/>
    {(p.routes ?? []).map((r, i) => {
      const a = points.find((l) => l.id === r.from), b = points.find((l) => l.id === r.to);
      if (!a || !b) throw new Error('Director map route has unknown endpoint.');
      const q = projection([a.lon,a.lat])!, t = projection([b.lon,b.lat])!;
      return <path key={i} d={`M${q[0]} ${q[1]}Q${(q[0]+t[0])/2} ${(q[1]+t[1])/2-35} ${t[0]} ${t[1]}`} fill="none" stroke={INK.cinnabar} strokeWidth="4" strokeLinecap="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1-progress}/>;
    })}
    {points.map((l,i) => {const q=projection([l.lon,l.lat])!,box=labels[i];const endX=clamp(q[0],box.x-380+4,box.x-380+box.width-4),endY=clamp(q[1],box.y-370+4,box.y-370+box.height-4); return <g key={l.id} opacity={i === 0 ? 1 : ease((progress - .75) / .25)}><path d={`M${q[0]} ${q[1]}L${endX} ${endY}`} fill="none" stroke={INK.muted} strokeWidth="1"/><circle cx={q[0]} cy={q[1]} r="7" fill={INK.cinnabar} stroke={INK.light} strokeWidth="3"/></g>;})}
    <AssetTypography state={state}/>
  </g>;
}

export function HistoryAsset({state, land}: {state: ObjectFrame; land?: GeoPermissibleObjects}) {
  const p = state.object.parameters ?? {};
  switch (state.object.asset_id) {
    case 'actor.person': return <Person state={state}/>;
    case 'actor.envoy': return <Person state={state} courier/>;
    case 'actor.horse': return <Horse state={state}/>;
    case 'actor.caravan': return <g><g transform="translate(-77 0) scale(.75)"><Horse state={state}/></g><g transform="translate(91 -10) scale(.65)"><Horse state={state} packed/></g></g>;
    case 'prop.gate': return <Gate open={state.gateOpen}/>;
    case 'prop.document': return <g transform={`rotate(${-state.handover*5})`}><Scroll document open={state.gateOpen}/></g>;
    case 'prop.scroll': return <Scroll open={Math.max(state.scrollOpen,state.gateOpen)}/>;
    case 'prop.seal': return <Seal progress={state.stamp}/>;
    case 'prop.flag': return <g><path d="M-30 0V-227" stroke={INK.dark} strokeWidth="5"/><g opacity={state.action === 'draw' ? state.draw : 1} transform={`translate(-30 -215) scale(${state.action === 'draw' ? Math.max(.01,state.draw) : 1} 1) translate(30 215)`}><path d="M-30-221Q12-236 66-214L42-171Q5-189-30-172Z" fill={INK.cinnabar} {...line}/><path d="M-15-209L18-205M-15-198L11-195" stroke={INK.gold} strokeWidth="4"/></g><path d="M-39-222L-30-236L-21-222Z" fill={INK.gold}/></g>;
    case 'info.map': return <MapAsset state={state} land={land}/>;
    case 'info.timeline': return <g>
      <path d="M-345-39H345" stroke={INK.muted} strokeWidth="2" opacity=".4"/><path d="M-345-39H345" stroke={INK.cinnabar} strokeWidth="4" pathLength="1" strokeDasharray="1" strokeDashoffset={1-(state.draw || (state.action === 'draw' ? 0 : 1))}/>
      <circle cx="0" cy="-39" r="9" fill={INK.cinnabar}/><path d="M0-57V-81" stroke={INK.cinnabar} strokeWidth="2"/>
      <AssetTypography state={state}/>
    </g>;
    case 'info.portrait': return <g><circle cy="-160" r="85" fill="#d2d3bc" opacity=".5"/><g transform="translate(0 -52) scale(.65)"><Person state={state}/></g><AssetTypography state={state}/></g>;
    default: throw new Error(`Unsupported director asset: ${state.object.asset_id}`);
  }
}
