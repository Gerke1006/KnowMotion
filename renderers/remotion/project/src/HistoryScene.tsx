import React, {useEffect, useMemo, useState} from 'react';
import {AbsoluteFill, cancelRender, continueRender, delayRender, Img, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {geoEquirectangular, geoGraticule10, geoPath} from 'd3-geo';
import type {GeoPermissibleObjects} from 'd3-geo';
import type {HistoryProps, MapParams, PersonParams, Source, TimelineParams} from './types';
import {audienceNote, captionAt, clamp, ease, layoutMapLabels, sortedEvents, yearLabel, yearOrdinal} from './data';

const C = {paper: '#f3efe5', ink: '#222c30', muted: '#69716a', red: '#a34b37', gold: '#b49358', rule: '#c9c8b8', land: '#d9ddcc'};
const fontStack = (english?: string, chinese?: string) => `"${english ?? 'Times New Roman'}", "${chinese ?? 'SimSun'}", serif`;
const short = (text: string, limit = 46) => text.length > limit ? text.slice(0, limit - 1) + '…' : text;
const lines = (text: string, length: number): string[] => {
  const result: string[] = [];
  const chars = [...text];
  for (let i = 0; i < chars.length; i += length) result.push(chars.slice(i, i + length).join(''));
  return result;
};

function Paper({width, height}: {width: number; height: number}) {
  return <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} style={{position: 'absolute', inset: 0}}>
    <defs>
      <pattern id="paper-grid" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M36 0H0V36" fill="none" stroke={C.rule} strokeWidth=".6" opacity=".24"/></pattern>
      <pattern id="paper-grain" width="83" height="71" patternUnits="userSpaceOnUse"><path d="M4 7h1M18 42h2M56 15h1M39 64h2M72 48h1" stroke="#68665a" strokeWidth=".7" opacity=".14"/></pattern>
      <radialGradient id="paper-light"><stop stopColor="#fffef8"/><stop offset="1" stopColor={C.paper}/></radialGradient>
    </defs>
    <rect width="100%" height="100%" fill="url(#paper-light)"/><rect width="100%" height="100%" fill="url(#paper-grid)"/><rect width="100%" height="100%" fill="url(#paper-grain)"/>
    <path d={`M0 ${height * .78}L${width} ${height * .72}V${height}H0Z`} fill="#dad7c8" opacity=".12"/>
  </svg>;
}

function MapVisual({params: p, land, width: w, height: h, progress, portrait}: {params: MapParams; land: GeoPermissibleObjects; width: number; height: number; progress: number; portrait: boolean}) {
  const mapW = portrait ? w : w * .735;
  const mapH = portrait ? h * .66 : h;
  const v = p.viewport ?? {
    west: Math.max(-179, Math.min(...p.locations.map((l) => l.lon)) - 11),
    east: Math.min(179, Math.max(...p.locations.map((l) => l.lon)) + 11),
    south: Math.max(-80, Math.min(...p.locations.map((l) => l.lat)) - 9),
    north: Math.min(80, Math.max(...p.locations.map((l) => l.lat)) + 9),
  };
  const projection = useMemo(() => geoEquirectangular().center([(v.west + v.east) / 2, (v.south + v.north) / 2])
    .scale(Math.min((mapW - 85) / ((v.east - v.west) * Math.PI / 180), (mapH - 95) / ((v.north - v.south) * Math.PI / 180)))
    .translate([mapW / 2, mapH / 2]).clipExtent([[12, 12], [mapW - 12, mapH - 12]]), [v.west, v.east, v.south, v.north, mapW, mapH]);
  const path = geoPath(projection);
  const progressForRoutes = clamp((progress - .07) / .78);
  const active = Math.min(p.locations.length - 1, Math.floor(progressForRoutes * p.locations.length));
  const focus = p.locations[active];
  const panelX = portrait ? 15 : mapW + 24;
  const panelY = portrait ? mapH + 27 : 32;
  const panelW = portrait ? w - 30 : w - panelX - 10;
  const labelSize = portrait ? 20 : 19;
  const placedLabels = layoutMapLabels(p.locations.map((l) => {
    const point = projection([l.lon, l.lat])!;
    return {id: l.id, name: l.name, x: point[0], y: point[1]};
  }), mapW, mapH, labelSize);
  const nameLines = lines(focus.name, Math.max(7, Math.floor(panelW / 28)));
  const nameBottom = 83 + (nameLines.length - 1) * 34;
  const coordinateY = portrait ? 200 + (nameLines.length - 1) * 16 : h - 104;
  const descriptionY = nameBottom + (focus.year ? 69 : 42);
  const description = audienceNote(focus.description?.trim() || p.note?.trim(), '节点间的交流连接了更广阔的地域。');
  const descriptionLineCount = Math.max(1, Math.floor((coordinateY - 26 - descriptionY) / 27) + 1);
  const camera = 1.012 + ease(progress) * .015;
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{overflow: 'visible'}}>
    <defs><clipPath id="map-clip"><rect x="0" y="0" width={mapW} height={mapH} rx="2"/></clipPath></defs>
    <rect x="6" y="5" width={mapW} height={mapH} fill="#44412e" opacity=".07" transform="rotate(-.35)"/>
    <rect width={mapW} height={mapH} fill="#f9f7ee" stroke={C.rule}/>
    <g clipPath="url(#map-clip)">
      <g transform={`translate(${mapW / 2} ${mapH / 2}) scale(${camera}) translate(${-mapW / 2} ${-mapH / 2})`}>
        <path d={path(land) ?? ''} fill={C.land} stroke="#939b88" strokeWidth=".8"/>
        <path d={path(geoGraticule10()) ?? ''} fill="none" stroke="#aab5a5" strokeWidth=".65" strokeDasharray="3 5" opacity=".55"/>
        {(p.routes ?? []).map((route, i, routes) => {
          const a = p.locations.find((l) => l.id === route.from)!;
          const b = p.locations.find((l) => l.id === route.to)!;
          const [x1, y1] = projection([a.lon, a.lat])!;
          const [x2, y2] = projection([b.lon, b.lat])!;
          const bend = Math.min(38, Math.abs(x2 - x1) * .12);
          const d = `M${x1},${y1} Q${(x1 + x2) / 2},${(y1 + y2) / 2 - bend} ${x2},${y2}`;
          const reveal = ease(clamp(progressForRoutes * routes.length - i));
          return <g key={route.id ?? `${route.from}-${route.to}-${i}`}>
            <path d={d} fill="none" stroke={C.red} strokeWidth="1.6" strokeDasharray="3 5" opacity=".2"/>
            <path d={d} fill="none" stroke={C.red} strokeWidth="3" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - reveal} strokeLinecap="round"/>
          </g>;
        })}
        {p.locations.map((location, i) => {
          const point = projection([location.lon, location.lat])!;
          const pulse = i === active ? 1 + .12 * Math.sin(progress * Math.PI * 12) : 1;
          const box = placedLabels[i];
          const lineEndX = clamp(point[0], box.x + 4, box.x + box.width - 4);
          const lineEndY = clamp(point[1], box.y + 4, box.y + box.height - 4);
          return <g key={location.id} opacity={i <= active ? 1 : .64}>
            <path d={`M${point[0]} ${point[1]}L${lineEndX} ${lineEndY}`} stroke={C.muted} strokeWidth=".9" opacity=".7"/>
            <circle cx={point[0]} cy={point[1]} r={i === active ? 12 * pulse : 7} fill={C.red} opacity=".13"/>
            <circle cx={point[0]} cy={point[1]} r={i === active ? 5 : 3.5} fill={C.red} stroke="#fffdf7" strokeWidth="1.6"/>
            <rect x={box.x} y={box.y} width={box.width} height={box.height} fill="#f8f5e9" opacity=".96" rx="2"/>
            <text x={box.x + box.width / 2} y={box.y + labelSize + 2} textAnchor="middle" fill={C.ink} fontSize={labelSize}>{box.text}</text>
          </g>;
        })}
      </g>
    </g>
    <g transform={`translate(${panelX} ${panelY})`}>
      <path d={`M0 0H${panelW}`} stroke={C.red} strokeWidth="3"/>
      <text y="33" fontSize="15" fill={C.muted} letterSpacing="3">空间线索</text>
      {nameLines.map((line, i) => <text key={i} y={83 + i * 34} fontSize="28" fill={C.ink}>{line}</text>)}
      {focus.year && <text y={nameBottom + 32} fontSize="22" fill={C.red}>{typeof focus.year === 'number' ? yearLabel(focus.year) : focus.year}</text>}
      {lines(short(description, 88), portrait ? 25 : Math.max(9, Math.floor(panelW / 20))).slice(0, descriptionLineCount).map((line, i) => <text key={i} y={descriptionY + i * 27} fontSize="20" fill={C.ink}>{line}</text>)}
      <text y={coordinateY} fontSize="15" fill={C.muted}>{Math.abs(focus.lon).toFixed(1)}° {focus.lon < 0 ? 'W' : 'E'} · {Math.abs(focus.lat).toFixed(1)}° {focus.lat < 0 ? 'S' : 'N'}</text>
      <text y={coordinateY + 32} fontSize="14" fill={C.muted}>地点为近似定位 · 路线为交流示意</text>
    </g>
    <text x="14" y={mapH - 17} fontSize="13" fill={C.muted}>NATURAL EARTH / 陆地轮廓底图，不表示古代疆界</text>
    <g transform={`translate(${mapW - 35},35)`}><path d="M0 18V-2M-4 4L0-5L4 4" stroke={C.ink} fill="none"/><text y="-12" textAnchor="middle" fontSize="11" fill={C.ink}>N</text></g>
  </svg>;
}

function TimelineVisual({params: p, width: w, height: h, progress, portrait}: {params: TimelineParams; width: number; height: number; progress: number; portrait: boolean}) {
  const events = sortedEvents(p.events);
  const first = p.range?.[0] ?? events[0].year;
  const last = p.range?.[1] ?? events.at(-1)!.year;
  const span = Math.max(1, yearOrdinal(last) - yearOrdinal(first));
  const active = Math.min(events.length - 1, Math.floor(clamp((progress - .04) / .92) * events.length));
  const focused = events[active];
  const left = portrait ? 56 : 45;
  const right = w - 45;
  const baseline = portrait ? 200 : h * .52;
  const x = (year: number) => left + clamp((yearOrdinal(year) - yearOrdinal(first)) / span) * (right - left);
  const y = (index: number) => portrait ? 216 + index * Math.min(114, (h - 260) / Math.max(1, events.length - 1)) : baseline;
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
    <text x={portrait ? 20 : 35} y="54" fontSize={focused.date_label && focused.date_label.length > 12 ? 30 : portrait ? 45 : 48} fill={C.red}>{focused.date_label ?? yearLabel(focused.year)}</text>
    <text x={portrait ? 20 : 535} y={portrait ? 107 : 53} fontSize={portrait ? 27 : 30} fill={C.ink}>{short(focused.label, portrait ? 24 : 19)}</text>
    <text x={portrait ? 20 : 35} y={portrait ? 151 : 95} fontSize="18" fill={C.muted}>{short(audienceNote(p.note, '以年代定位事件，以史料判断联系。'), portrait ? 30 : 58)}</text>
    {portrait ? <path d={`M${left} ${baseline}V${h - 30}`} stroke={C.rule} strokeWidth="2"/> : <path d={`M${left} ${baseline}H${right}`} stroke={C.rule} strokeWidth="2"/>}
    {portrait ? <path d={`M${left} ${baseline}V${baseline + ease(progress) * (y(events.length - 1) - baseline)}`} stroke={C.red} strokeWidth="3"/> : <path d={`M${left} ${baseline}H${left + ease(progress) * (right - left)}`} stroke={C.red} strokeWidth="3"/>}
    {events.map((event, i) => {
      const px = portrait ? left : x(event.year);
      const py = y(i);
      const isActive = i === active;
      const above = i % 2 === 0;
      const labelY = baseline + (above ? -65 : 74);
      const labelX = portrait ? 95 : clamp(px, 90, w - 100);
      // Text lanes avoid identical and tightly clustered years overwriting one another.
      const cell = (w - 50) / events.length;
      const laneX = 25 + cell * (i + .5);
      return <g key={`${event.year}-${i}`} opacity={i <= active ? 1 : .52}>
        {!portrait && <path d={`M${px} ${py}V${above ? labelY + 20 : labelY - 31}L${laneX} ${above ? labelY + 20 : labelY - 31}`} fill="none" stroke={C.rule} strokeWidth="1.2"/>}
        <circle cx={px} cy={py} r={isActive ? 11 : 7} fill={isActive ? C.red : C.paper} stroke={C.red} strokeWidth="2"/>
        <circle cx={px} cy={py} r={isActive ? 18 : 0} fill="none" stroke={C.red} opacity=".15"/>
        <text x={portrait ? labelX : laneX} y={portrait ? py - 9 : labelY - 17} fontSize={portrait ? 23 : Math.min(23, cell / Math.max(6, (event.date_label?.length ?? 0)))} fill={C.red} textAnchor={portrait ? 'start' : 'middle'}>{event.date_label ?? yearLabel(event.year)}</text>
        {lines(event.label, portrait ? 17 : Math.max(6, Math.floor(cell / 23))).slice(0, 2).map((line, j) => <text key={j} x={portrait ? labelX : laneX} y={(portrait ? py + 23 : labelY + 14) + j * 27} fontSize={portrait ? 22 : 21} fill={C.ink} textAnchor={portrait ? 'start' : 'middle'}>{line}</text>)}
      </g>;
    })}
    {!portrait && focused.detail && <g transform={`translate(35 ${h - 47})`}><path d="M0-17V16" stroke={C.red} strokeWidth="3"/><text x="17" y="7" fontSize="23" fill={C.ink}>{short(focused.detail, 42)}</text></g>}
  </svg>;
}

function PersonVisual({params: p, width: w, height: h, progress, portrait, imageCaption}: {params: PersonParams; width: number; height: number; progress: number; portrait: boolean; imageCaption?: string}) {
  const cardW = portrait ? Math.min(310, w * .65) : w * .32;
  const cardH = portrait ? h * .40 : h * .90;
  const cardX = portrait ? (w - cardW) / 2 : 26;
  const cardY = 12;
  const rightX = portrait ? 22 : cardW + 75;
  const rightY = portrait ? cardH + 57 : 52;
  const rightW = portrait ? w - 44 : w - rightX - 20;
  const rise = (1 - ease(progress / .08)) * 18;
  const angle = -.8 + ease(progress) * .6;
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
    <g transform={`translate(${cardX},${cardY + rise}) rotate(${angle},${cardW / 2},${cardH / 2})`}>
      <rect x="5" y="7" width={cardW} height={cardH} fill="#343227" opacity=".10"/>
      <rect width={cardW} height={cardH} fill="#fefcf5" stroke={C.rule}/>
      <path d={`M${cardW * .18}-9L${cardW * .68}-13L${cardW * .70}11L${cardW * .2}15Z`} fill="#d9cb9c" opacity=".63"/>
      <rect x="18" y="22" width={cardW - 36} height={cardH - 88} fill="#dce0d4"/>
      {p.portrait_asset ? <foreignObject x="18" y="22" width={cardW - 36} height={cardH - 88}><Img src={staticFile(p.portrait_asset)} style={{width: '100%', height: '100%', objectFit: 'contain', filter: 'grayscale(1) sepia(.25)'}}/></foreignObject> : <g>
        <circle cx={cardW / 2} cy={(cardH - 52) / 2} r={Math.min(cardW * .31, cardH * .28)} fill="none" stroke={C.muted} strokeWidth="1.2"/>
        <circle cx={cardW / 2} cy={(cardH - 52) / 2} r={Math.min(cardW * .28, cardH * .25)} fill="none" stroke={C.muted} opacity=".3"/>
        <text x={cardW / 2} y={(cardH - 52) / 2 + 26} fontSize={Math.min(84, (cardW - 80) / Math.min(3, p.name.length))} fill={C.ink} textAnchor="middle">{p.name.slice(0, 3)}</text>
      </g>}
      {lines(p.portrait_asset ? imageCaption ?? '历史人物资料图' : '人物符号示意 · 非历史肖像', Math.floor((cardW - 25) / 14)).slice(0, 2).map((line, i) => <text key={i} x={cardW / 2} y={cardH - 48 + i * 19} fontSize="14" fill={C.muted} textAnchor="middle">{line}</text>)}
      <text x={cardW / 2} y={cardH - 10} fontSize="10" fill={C.muted} letterSpacing="3" textAnchor="middle">PERSON / ARCHIVE</text>
    </g>
    {!portrait && p.related?.length ? <text x={cardX} y={cardH + 40} fontSize="15" fill={C.muted}>{short(p.related.map((r) => `${r.name}·${r.relation}`).join(' / '), 24)}</text> : null}
    <g transform={`translate(${rightX} ${rightY})`}>
      <text y="0" fontSize={portrait ? 42 : 48} fill={C.ink}>{p.name}</text>
      <text y="37" fontSize="23" fill={C.red}>{short(p.role, 22)}</text>
      {p.years && <text y="69" fontSize="20" fill={C.muted}>{p.years}</text>}
      {p.facts.map((fact, i) => {
        const reveal = ease((progress - .07 - i * .13) / .07);
        const rowH = portrait ? 76 : Math.min(83, (h - 135) / p.facts.length);
        const y = (p.years ? 110 : 95) + i * rowH;
        return <g key={i} opacity={reveal} transform={`translate(${(1 - reveal) * 14} ${y})`}>
          <text x="0" y="0" fontSize="15" fill={C.red}>{String(i + 1).padStart(2, '0')}</text>
          <path d={`M35 13H${rightW}`} stroke={C.rule} strokeWidth=".8"/>
          {lines(fact, Math.max(12, Math.floor((rightW - 44) / 23))).slice(0, 2).map((line, j) => <text key={j} x="41" y={j * 28} fontSize="23" fill={C.ink}>{line}</text>)}
        </g>;
      })}
    </g>
  </svg>;
}

function citedSources(props: HistoryProps): Source[] {
  const sources = props.sources ?? props.scene.extensions?.historical_sources ?? [];
  const component = props.scene.components[0];
  const ids = new Set(component.parameters.source_ids ?? []);
  if (!ids.size) return sources.slice(0, 2);
  return sources.filter((s) => s.id && ids.has(s.id)).slice(0, 2);
}

export const HistoryScene: React.FC<HistoryProps> = (props) => {
  const frame = useCurrentFrame();
  const {width, height, fps, durationInFrames} = useVideoConfig();
  const [fontHandle] = useState(() => delayRender('Loading local Chinese and Roman fonts'));
  useEffect(() => {
    Promise.all([
      document.fonts.load(`30px "${props.fonts?.chinese ?? 'SimSun'}"`, '历史'),
      document.fonts.load(`700 30px "${props.fonts?.subtitle ?? 'Microsoft YaHei'}"`, '历史'),
      document.fonts.ready,
    ]).then(() => continueRender(fontHandle)).catch(cancelRender);
  }, [fontHandle, props.fonts?.chinese, props.fonts?.subtitle]);
  const portrait = height > width * 1.15;
  const logicalW = portrait ? 720 : 1280;
  const scale = width / logicalW;
  const logicalH = height / scale;
  const margin = portrait ? 34 : 68;
  const mainW = logicalW - margin * 2;
  const contentY = portrait ? 220 : 172;
  const contentH = logicalH - contentY - (portrait ? 245 : 158);
  const progress = clamp(frame / Math.max(1, durationInFrames - 1));
  const seconds = frame / fps;
  const scene = props.scene;
  const component = scene.components[0];
  const typeLabel = {'history.map': '空间 / MAP', 'history.timeline': '年代 / TIMELINE', 'history.person': '人物 / PORTRAIT'}[component.id];
  const page = captionAt(scene.narration ?? '', seconds, scene.audio?.narration_offset ?? 0,
    scene.audio?.narration_duration ?? scene.duration, portrait ? 20 : 32);
  const sources = citedSources(props);
  return <AbsoluteFill style={{background: C.paper, overflow: 'hidden', fontFamily: fontStack(props.fonts?.english, props.fonts?.chinese)}}>
    <div style={{width: logicalW, height: logicalH, position: 'absolute', transform: `scale(${scale})`, transformOrigin: 'top left', color: C.ink}}>
      <Paper width={logicalW} height={logicalH}/>
      <div style={{position: 'absolute', top: 28, left: margin, right: margin, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 14, color: C.muted, letterSpacing: 2}}>
        <span>HISTORY / 历史札记</span><span>{typeLabel}</span>
      </div>
      <div style={{position: 'absolute', top: 60, left: margin, right: margin, fontSize: portrait ? 40 : Math.min(44, mainW / Math.max(1, (scene.title?.length ?? 16)) * 1.6), lineHeight: 1.24, maxHeight: portrait ? 115 : 65}}>{scene.title}</div>
      <div style={{position: 'absolute', top: portrait ? 185 : 134, left: margin, width: mainW, height: 1, background: C.rule}}/>
      <div style={{position: 'absolute', top: portrait ? 182 : 131, left: margin, width: 94 + progress * 72, height: 4, background: C.red}}/>
      <div style={{position: 'absolute', left: margin, top: contentY, width: mainW, height: contentH}}>
        {component.id === 'history.map' && props._land && <MapVisual params={component.parameters} land={props._land} width={mainW} height={contentH} progress={progress} portrait={portrait}/>}
        {component.id === 'history.timeline' && <TimelineVisual params={component.parameters} width={mainW} height={contentH} progress={progress} portrait={portrait}/>}
        {component.id === 'history.person' && <PersonVisual params={component.parameters} width={mainW} height={contentH} progress={progress} portrait={portrait} imageCaption={props._portrait?.caption}/>}
      </div>
      <div style={{position: 'absolute', left: margin, right: margin, bottom: portrait ? 167 : 117, fontSize: portrait ? 14 : 13, lineHeight: 1.4, color: C.muted, borderTop: `1px solid ${C.rule}`, paddingTop: 10}}>
        {sources.length ? sources.map((s) => `${s.id ? `[${s.id}] ` : ''}${short(s.title ?? s.provider ?? '历史资料', portrait ? 35 : 58)}`).join('   /   ') : '历史材料依照讲稿来源整理'}
      </div>
      {page && <div style={{position: 'absolute', left: margin - 5, right: margin - 5, bottom: portrait ? 42 : 23, minHeight: portrait ? 84 : 65, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '6px 18px', boxSizing: 'border-box', borderRadius: 3, background: 'rgba(26,36,42,.92)', color: props.fonts?.subtitle_color ?? '#fff', fontFamily: fontStack(props.fonts?.english, props.fonts?.subtitle ?? 'Microsoft YaHei'), fontWeight: 700, fontSize: portrait ? 31 : 33, lineHeight: 1.4, WebkitTextStroke: `${(props.fonts?.outline_width ?? 5) / 2}px ${props.fonts?.outline_color ?? '#161044'}`, paintOrder: 'stroke fill'}}>{page}</div>}
      <div style={{position: 'absolute', bottom: 0, height: 3, width: logicalW * progress, background: C.red}}/>
    </div>
  </AbsoluteFill>;
};
