import assert from 'node:assert/strict';
import test from 'node:test';
import {auditDirector, captionLayout, evaluateDirector, keywordLayout, pathPoint, validateDirector} from '../src/directorData';
import type {DirectorSceneData} from '../src/directorTypes';
import type {AssetId} from '../src/directorTypes';

function fixture(): DirectorSceneData {
  return {protocol:'history-director-v2',scene_id:'fixture',segment_id:'unit',title:'Unit',narration:'甲走向乙，文书随后展开。',duration:8,fps:30,environment:'road',sources:[],
    objects:[{id:'traveler',asset_id:'actor.envoy',x:.3,y:.75,scale:1,label:'行者'}, {id:'scroll',asset_id:'prop.scroll',x:.6,y:.7,scale:1}],
    captions:[{text:'甲走向乙',start:.15,end:3.7},{text:'文书随后展开',start:4.1,end:7.6}],
    beats:[{id:'walk',start:0,end:4,anchor_time:.15,visible_ids:['traveler'],focus_id:'traveler',keywords:['行者'],camera:{x:.5,y:.5,zoom:1},actions:[{target_id:'traveler',kind:'walk',start:0,end:4,from:{x:.3,y:.75,scale:1},to:{x:.55,y:.75,scale:1}}]},
      {id:'unroll',start:4,end:8,anchor_time:4,visible_ids:['scroll'],focus_id:'scroll',keywords:['文书'],camera:{x:.5,y:.5,zoom:1.05},actions:[{target_id:'scroll',kind:'unroll',start:4,end:8,from:{x:.6,y:.7,scale:1},to:{x:.6,y:.7,scale:1}}]}]};
}

test('director uses observed caption windows and never exposes future objects', () => {
  const d=fixture(); validateDirector(d);
  assert.equal(evaluateDirector(d,.1).caption,''); assert.equal(evaluateDirector(d,1).caption,'甲走向乙');
  assert.deepEqual(evaluateDirector(d,2).objects.map((o)=>o.object.id),['traveler']);
  assert.deepEqual(evaluateDirector(d,4).objects.map((o)=>o.object.id),['scroll']);
  assert.deepEqual(evaluateDirector(d,8).objects,[]); assert.equal(evaluateDirector(d,7.8).caption,'');
});
test('movement follows compiled coordinates and is deterministic under out-of-order seeking', () => {
  const d=fixture(); const at=evaluateDirector(d,2);
  assert.equal(at.objects[0].x,.42500000000000004);
  evaluateDirector(d,7); evaluateDirector(d,.2);
  assert.deepEqual(evaluateDirector(d,2),at);
  assert.deepEqual(pathPoint([{x:0,y:0},{x:.2,y:0},{x:1,y:0}],.5),{x:.5,y:0});
});
test('articulated states persist, close resets an unrolled scroll', () => {
  const d=fixture(); const b=d.beats[1];
  d.beats.push({...b,id:'close',start:8,end:10,actions:[{...b.actions[0],kind:'close',start:8,end:10}]}); d.duration=10;
  assert.equal(evaluateDirector(d,7).objects[0].scrollOpen,1);
  assert.ok(evaluateDirector(d,8.5).objects[0].scrollOpen<1);
  assert.equal(evaluateDirector(d,9.8).objects[0].scrollOpen,0);
});
test('unsupported action/asset and information density violations fail clearly', () => {
  const d=fixture(); d.beats[0].actions[0].kind='stamp'; assert.throws(()=>validateDirector(d),/Unsupported action/);
  const e=fixture(); e.beats[0].keywords=['a','b','c']; assert.throws(()=>validateDirector(e),/density/);
  const f=fixture(); f.beats[0].visible_ids=['missing']; assert.throws(()=>validateDirector(f),/visible/);
});
test('frame audit shares renderer evaluation, reports complete action consumption', () => {
  const report=auditDirector(fixture());
  assert.equal(report.frame_count,240); assert.equal(report.maximum_visible_groups,1); assert.deepEqual(report.unconsumed_actions,[]);
  assert.ok(report.frames.slice(0,120).every((f)=>!f.groups.includes('scroll')));
  assert.ok(report.frames.slice(120).every((f)=>!f.groups.includes('traveler')));
});
test('two-line observed captions and keyword geometry remain in the output frame',()=>{
  for(const [w,h] of [[1280,720],[720,1280]]){
    const c=captionLayout('第一行字幕内容\n第二行字幕内容',w,h);
    assert.equal(c.text.split('\n').length,2);assert.ok(c.box.y>0&&c.box.y+c.box.height<h);
    for(const k of keywordLayout(['主题一','主题二'],w,h))assert.ok(k.box.x>=0&&k.box.x+k.box.width<=w);
  }
});
test('seal contact is synchronous with the observed anchor rather than delayed after it',()=>{
  const d=fixture();d.objects[0].asset_id='prop.seal';d.beats[0].actions[0].kind='stamp';
  assert.ok(evaluateDirector(d,.1).objects[0].stamp<0);
  assert.equal(evaluateDirector(d,.15).objects[0].stamp,0);
  assert.equal(evaluateDirector(d,.15).objects[0].opacity,1);
  assert.equal(evaluateDirector(d,1).objects[0].stamp,.24);
});

function infoFixture(asset_id:AssetId,parameters:Record<string,unknown>):DirectorSceneData{
  const d=fixture();d.duration=3;d.captions=[];
  d.objects=[{id:'information',asset_id,x:.5,y:.7,scale:1,parameters}];
  d.beats=[{id:'information',start:0,end:3,visible_ids:['information'],focus_id:'information',keywords:[],camera:{x:.5,y:.5,zoom:1},actions:[]}];
  return d;
}
const mapParameters=()=>({locations:[{id:'east',name:'东城（近似位置）',lon:100,lat:30},{id:'west',name:'西城',lon:80,lat:35}],routes:[{from:'east',to:'west'}]});

test('every map, timeline and portrait interior text node participates in frame geometry',()=>{
  const cases:[AssetId,Record<string,unknown>,string[]][]=[
    ['info.map',mapParameters(),['map_label','map_note']],
    ['info.timeline',{year:-200,date_label:'约公元前二世纪',label:'某次往来'},['timeline_date','timeline_label']],
    ['info.portrait',{name:'甲君',role:'远行者'},['portrait_name','portrait_role','portrait_note']],
  ];
  for(const [id,parameters,kinds] of cases){
    const report=auditDirector(infoFixture(id,parameters));
    assert.equal(report.passed,true,JSON.stringify(report.issues.slice(0,2)));
    for(const kind of kinds)assert.ok(report.frames[30].text_boxes.some(t=>t.kind===kind),`${id}: ${kind}`);
  }
});
test('interior text bounds, cross-object overlaps and complete-field character limits are enforced',()=>{
  const offscreen=infoFixture('info.timeline',{year:100,date_label:'约一世纪',label:'某事件'});offscreen.objects[0].x=.05;
  assert.ok(auditDirector(offscreen).issues.some(i=>i.kind==='text_outside_frame'));
  const overlap=infoFixture('info.portrait',{name:'甲君',role:'行者'});
  overlap.objects.push({...overlap.objects[0],id:'second'});overlap.beats[0].visible_ids.push('second');
  assert.ok(auditDirector(overlap).issues.some(i=>i.kind==='text_overlap'));
  const longMap=mapParameters();longMap.locations[0].name='地'.repeat(13);
  for(const d of [infoFixture('info.map',longMap),infoFixture('info.timeline',{year:1,date_label:'约'.repeat(41),label:'事'.repeat(13)}),infoFixture('info.portrait',{name:'人'.repeat(11),role:'职'.repeat(17)})]){
    const report=auditDirector(d);assert.equal(report.passed,false);assert.ok(report.issues.some(i=>i.kind==='text_character_limit'));
  }
});
test('semantic gaps use final playback seconds and exclude subtitle changes or camera drift',()=>{
  const d=infoFixture('info.timeline',{year:1,date_label:'一世纪',label:'某事件'});d.duration=4.5;d.beats[0].end=4.5;d.beats[0].camera.zoom=1.2;
  d.captions=[{text:'第一句',start:.1,end:2},{text:'第二句',start:2,end:4.4}];
  const normal=auditDirector(d,30,1280,720,1),fast=auditDirector(d,30,1280,720,1.15);
  assert.ok(normal.issues.some(i=>i.kind==='semantic_gap'));
  assert.ok(!fast.issues.some(i=>i.kind==='semantic_gap'));
  assert.equal(normal.maximum_unchanged_semantic_seconds/1.15,fast.maximum_unchanged_semantic_seconds);
  assert.ok(fast.maximum_unchanged_semantic_seconds<4);
});

test('a late opening entrance and its keywords remain hidden while static scenery is visible',()=>{
  const d=fixture();const b=d.beats[0];b.anchor_time=2;b.visible_ids=['traveler','scroll'];b.keywords=['新信息'];
  b.actions[0]={...b.actions[0],kind:'enter',start:2};
  validateDirector(d);
  for(const time of [.1,.5,1.5,2-1/30]){
    const state=evaluateDirector(d,time);
    assert.equal(state.objects.find(o=>o.object.id==='traveler')!.opacity,0);
    assert.ok(state.objects.find(o=>o.object.id==='scroll')!.opacity>0);
    assert.deepEqual(state.keywords,[]);assert.deepEqual(state.consumed,[]);
  }
  assert.deepEqual(evaluateDirector(d,2).keywords,['新信息']);
  assert.equal(evaluateDirector(d,2).objects[0].opacity,0);
  assert.ok(evaluateDirector(d,2.25).objects[0].opacity>0);
  const report=auditDirector(d);
  assert.ok(report.frames.slice(0,60).every(f=>!f.groups.includes('traveler')&&f.keywords.length===0));
});

test('late action visibility is pure under backward seeks and stamp still contacts at its anchor',()=>{
  const d=fixture();d.beats[0].anchor_time=2;d.beats[0].actions[0]={...d.beats[0].actions[0],kind:'enter',start:2};
  const original=structuredClone(d),before=evaluateDirector(d,1),during=evaluateDirector(d,2.25);
  evaluateDirector(d,7);evaluateDirector(d,3.5);
  assert.deepEqual(evaluateDirector(d,1),before);assert.deepEqual(evaluateDirector(d,2.25),during);assert.deepEqual(d,original);
  d.objects[0].asset_id='prop.seal';d.beats[0].actions[0].kind='stamp';
  assert.equal(evaluateDirector(d,1.9).objects[0].stamp,-.18);
  assert.equal(evaluateDirector(d,2).objects[0].stamp,0);
  assert.equal(evaluateDirector(d,2).objects[0].opacity,1);
  assert.equal(evaluateDirector(d,2.5).objects[0].stamp,.24);
});
