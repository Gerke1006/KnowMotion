import assert from 'node:assert/strict';
import test from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {HistoryCaption,historyFontStack} from '../src/HistoryTypography';
import {Scenery,sceneryTransform} from '../src/Scenery';
import {captionLayout,evaluateDirector} from '../src/directorData';
import {HistoryAsset} from '../src/HistoryAssets';
import type {DirectorSceneData} from '../src/directorTypes';

test('rendered caption uses audit geometry, Heavy serif text and a configurable translucent backing',()=>{
  const text='一句\n旁白',geometry=captionLayout(text);
  const html=renderToStaticMarkup(createElement(HistoryCaption,{text,width:1280,height:720,fonts:{background_opacity:.21}}));
  assert.ok(html.includes(`width="${geometry.box.width}" height="${geometry.box.height}"`));
  assert.ok(html.includes(`textLength="${geometry.lineWidths[0]}"`));
  assert.ok(html.includes('opacity="0.21"'));assert.ok(html.includes('stroke-width="1"'));
  assert.ok(html.includes('font-weight:900'));assert.ok(html.includes('History Serif'));assert.ok(html.includes('一句旁白'));
  assert.equal((html.match(/<text /g)??[]).length,1);
  const fallback=renderToStaticMarkup(createElement(HistoryCaption,{text,width:1280,height:720,fonts:{outline_width:5,outline_color:'#161044'}}));
  assert.ok(fallback.includes('opacity="0.18"'));assert.ok(fallback.includes('stroke-width="1.2"'));assert.ok(!fallback.includes('#161044'));
  assert.equal(historyFontStack('Times New Roman','SimSun'),'"Times New Roman", "SimSun", serif');
});

test('six environments have distinct geometry, three deterministic depth layers and no narrative objects or text',()=>{
  const environments:DirectorSceneData['environment'][]=['mountains','road','desert','city_gate','interior','map'];
  const camera={x:.55,y:.47,zoom:1.1};const geometries:string[]=[];
  for(const environment of environments){
    const render=()=>renderToStaticMarkup(createElement('svg',{},createElement(Scenery,{environment,camera})));
    const html=render();
    assert.equal((html.match(/data-depth=/g)??[]).length,3);
    assert.ok(!/<text[ >]|data-joint=|data-asset=/.test(html));
    const geometry=[...html.matchAll(/ d="([^"]+)"/g)].map(m=>m[1]).join('|');
    assert.ok(!geometries.includes(geometry));geometries.push(geometry);
    assert.equal(render(),html);
  }
  assert.notEqual(sceneryTransform(camera,.16),sceneryTransform(camera,.8));
  assert.ok(sceneryTransform({x:.5,y:.5,zoom:1},.8).includes('translate(0 0)'));
});

test('gesture changes the rendered forearm and head joints without adding a prop or changing body scale',()=>{
  const d:DirectorSceneData={protocol:'history-director-v2',scene_id:'fixture',segment_id:'unit',title:'讲述',narration:'人物讲述。',duration:3,fps:30,environment:'interior',sources:[],captions:[],
    objects:[{id:'speaker',asset_id:'actor.person',x:.5,y:.75,scale:1}],
    beats:[{id:'speak',start:0,end:3,visible_ids:['speaker'],focus_id:'speaker',keywords:[],camera:{x:.5,y:.5,zoom:1},actions:[{target_id:'speaker',kind:'gesture',start:.5,end:2.5,from:{x:.5,y:.75,scale:1},to:{x:.5,y:.75,scale:1}}]}]};
  const idle=renderToStaticMarkup(createElement('svg',{},createElement(HistoryAsset,{state:evaluateDirector(d,.25).objects[0]})));
  const active=renderToStaticMarkup(createElement('svg',{},createElement(HistoryAsset,{state:evaluateDirector(d,1.3).objects[0]})));
  assert.ok(idle.includes('data-joint="forearm" transform="rotate(0 30 -119)"'));
  assert.ok(!active.includes('data-joint="forearm" transform="rotate(0 30 -119)"'));
  assert.ok(!active.includes('data-joint="head" transform="rotate(0 0 -165)"'));
  assert.equal((idle.match(/<path /g)??[]).length,(active.match(/<path /g)??[]).length);
  assert.equal(evaluateDirector(d,1.3).objects[0].scale,1);
});
