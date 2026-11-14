import {geoEquirectangular} from 'd3-geo';
import {clamp,ease,layoutMapLabels,mapLabel,yearLabel} from './data';
import type {MapParams} from './types';
import type {ObjectFrame} from './directorTypes';

export type TextBox={x:number;y:number;width:number;height:number};
export type AssetTextSpec={id:string;kind:string;text:string;x:number;y:number;fontSize:number;width:number;anchor:'middle'|'start';opacity:number;limit:number;stroke:boolean;box:TextBox};
export const textWidth=(text:string,size:number)=>[...text].reduce((sum,char)=>sum+size*(char.charCodeAt(0)<128?.58:1),0);
const textSpec=(id:string,kind:string,text:string,x:number,y:number,fontSize:number,limit:number,anchor:'middle'|'start'='middle',opacity=1,stroke=false):AssetTextSpec=>{
  const width=textWidth(text,fontSize),pad=stroke?3:0;
  return{id,kind,text,x,y,fontSize,width,anchor,opacity,limit,stroke,box:{x:(anchor==='middle'?x-width/2:x)-pad,y:y-fontSize*.95-pad,width:width+pad*2,height:fontSize*1.2+pad*2}};
};
const chunks=(text:string,size:number)=>{const chars=[...text],out:string[]=[];for(let i=0;i<chars.length;i+=size)out.push(chars.slice(i,i+size).join(''));return out;};

/** Shared map projection and stable label placement: the SVG and audit use these exact values. */
export function directorMapGeometry(p:MapParams){
  const points=p.locations;
  if(!Array.isArray(points)||points.length!==2)throw new Error('Director map requires exactly two geographic endpoints.');
  const west=Math.min(...points.map(l=>l.lon))-9,east=Math.max(...points.map(l=>l.lon))+9;
  const south=Math.min(...points.map(l=>l.lat))-7,north=Math.max(...points.map(l=>l.lat))+7;
  const projection=geoEquirectangular().center([(west+east)/2,(south+north)/2]).scale(Math.min(680/((east-west)*Math.PI/180),270/((north-south)*Math.PI/180))).translate([0,-185]).clipExtent([[-370,-360],[370,-10]]);
  const anchors=points.map(l=>{const q=projection([l.lon,l.lat])!;return{id:l.id,name:l.name,x:q[0]+380,y:q[1]+370};});
  return{projection,points,labels:layoutMapLabels(anchors,760,370,24)};
}

/** Every text node inside an info asset is returned here; there are no unreported SVG text nodes. */
export function assetText(state:ObjectFrame):AssetTextSpec[]{
  const p=state.object.parameters??{};
  if(state.object.asset_id==='info.map'){
    const geometry=directorMapGeometry(p as unknown as MapParams);
    const progress=state.action==='draw'||state.draw>0?state.draw:1;
    const labels=geometry.labels.map((box,i)=>textSpec(`location:${box.id}`,'map_label',mapLabel(geometry.points[i].name),box.x-380+box.width/2,box.y-370+26,24,12,'middle',i===0?1:ease((progress-.75)/.25),true));
    return[...labels,textSpec('map-note','map_note','陆地轮廓 · 近似定位 / 交流路线示意，非古代疆界',-357,-19,14,48,'start')];
  }
  if(state.object.asset_id==='info.timeline'){
    const date=String(p.date_label??yearLabel(Number(p.year))),dateLines=chunks(date,20);
    const label=String(p.label??'');
    const size=dateLines.length>1?28:Math.min(42,640/Math.max(1,textWidth(date,1)));
    return[...dateLines.map((s,i)=>textSpec(`date:${i}`,'timeline_date',s,0,dateLines.length>1?-158+i*38:-112,size,40)),textSpec('event-label','timeline_label',label,0,-65,30,12)];
  }
  if(state.object.asset_id==='info.portrait'){
    const name=String(p.name??''),role=String(p.role??''),roleLines=chunks(role,8);
    return[textSpec('name','portrait_name',name,0,-244,Math.min(28,196/Math.max(1,textWidth(name,1))),10),
      ...roleLines.map((s,i)=>textSpec(`role:${i}`,'portrait_role',s,0,roleLines.length>1?-45+i*19:-27,16,16)),
      textSpec('portrait-note','portrait_note','人物符号 · 非历史肖像',0,-6,12,24)];
  }
  return[];
}

/** Full field limits are checked before wrapping, so splitting never conceals excessive content. */
export function assetTextLengths(state:ObjectFrame){
  const p=state.object.parameters??{};
  if(state.object.asset_id==='info.map')return (p.locations as MapParams['locations']).map(l=>({kind:'map_label',text:mapLabel(l.name),limit:12}));
  if(state.object.asset_id==='info.timeline')return[{kind:'timeline_date',text:String(p.date_label??yearLabel(Number(p.year))),limit:40},{kind:'timeline_label',text:String(p.label??''),limit:12}];
  if(state.object.asset_id==='info.portrait')return[{kind:'portrait_name',text:String(p.name??''),limit:10},{kind:'portrait_role',text:String(p.role??''),limit:16}];
  return[];
}
