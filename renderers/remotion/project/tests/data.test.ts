import assert from 'node:assert/strict';
import test from 'node:test';
import {audienceNote, captionAt, captionPages, layoutMapLabels, mapLabel, sortedEvents, validateProps, yearLabel, yearOrdinal} from '../src/data';
import type {HistoryProps} from '../src/types';

function fixture(): HistoryProps {
  return {scene: {scene_id: 'test', duration: 10, title: 'Unit fixture', components: [{id: 'history.map', parameters: {
    locations: [{id: 'a', name: 'A', lon: 100, lat: 30}, {id: 'b', name: 'B', lon: 80, lat: 40}], routes: [{from: 'a', to: 'b'}],
  }}]}, metadata: {width: 1280, height: 720, fps: 30}};
}

test('captions preserve text and do not leave punctuation alone', () => {
  for (const text of ['这'.repeat(28) + '。', '从长安出发，沿着道路向西。English words remain visible.']) {
    const pages = captionPages(text);
    assert.equal(pages.join(''), text);
    assert.ok(pages.every((p) => p.length <= 28 && p.length > 1));
  }
});
test('captions hide in both silent transition handles', () => {
  assert.equal(captionAt('旁白内容', .14, .15, 5), '');
  assert.equal(captionAt('旁白内容', .15, .15, 5), '旁白内容');
  assert.equal(captionAt('旁白内容', 5.14, .15, 5), '旁白内容');
  assert.equal(captionAt('旁白内容', 5.15, .15, 5), '');
});
test('BCE precedes CE without inventing a civil year zero', () => {
  assert.equal(yearOrdinal(1) - yearOrdinal(-1), 1);
  assert.equal(yearLabel(-138), '公元前 138');
  assert.throws(() => yearLabel(0));
  assert.deepEqual(sortedEvents([{year: 2, label: 'b'}, {year: -1, label: 'a'}]).map((e) => e.label), ['a', 'b']);
});
test('map rejects broken route links, impossible coordinates and duplicate ids', () => {
  validateProps(fixture());
  const broken = fixture(); const c = broken.scene.components[0];
  if (c.id !== 'history.map') throw new Error('fixture');
  c.parameters.routes![0].to = 'missing';
  assert.throws(() => validateProps(broken), /unknown/);
  c.parameters.routes = []; c.parameters.locations[0].lat = 100;
  assert.throws(() => validateProps(broken), /latitude/);
  c.parameters.locations[0].lat = 30; c.parameters.locations[1].id = 'a';
  assert.throws(() => validateProps(broken), /unique/);
});
test('untrusted portrait paths and unknown components are rejected', () => {
  const props = fixture();
  props.scene.components = [{id: 'history.person', parameters: {name: 'Test', role: 'Figure', facts: ['A'], portrait_asset: 'https://example.com/portrait.jpg'}}];
  assert.throws(() => validateProps(props), /approved local/);
  props.scene.components = [{id: 'untrusted.code', parameters: {}}] as never;
  assert.throws(() => validateProps(props), /Unsupported/);
});

test('live-map clustered labels avoid each other while anchors retain geography', () => {
  const anchors = [
    {id: 'changan', name: '长安（今西安附近）', x: 723, y: 205},
    {id: 'dunhuang', name: '敦煌', x: 614, y: 159},
    {id: 'kashgar', name: '喀什', x: 460, y: 165},
    {id: 'samarkand', name: '撒马尔罕', x: 402, y: 168},
    {id: 'balkh', name: '巴尔赫（巴克特拉附近）', x: 401, y: 199},
    {id: 'antioch', name: '安条克（今安塔基亚附近）', x: 168, y: 190},
    {id: 'alexandria', name: '亚历山大港', x: 117, y: 230},
  ];
  const labels = layoutMapLabels(anchors, 840, 390);
  assert.deepEqual(labels, layoutMapLabels(anchors, 840, 390));
  for (let i = 0; i < labels.length; i++) {
    const box = labels[i];
    assert.equal(box.anchorX, anchors[i].x); assert.equal(box.anchorY, anchors[i].y);
    assert.ok(box.x >= 0 && box.x + box.width <= 840 && box.y >= 0 && box.y + box.height <= 347);
    for (const other of labels.slice(i + 1)) {
      assert.ok(box.x + box.width <= other.x || other.x + other.width <= box.x || box.y + box.height <= other.y || other.y + other.height <= box.y,
        `labels ${box.id} and ${other.id} overlap`);
    }
  }
  assert.equal(mapLabel('长安（今西安附近）'), '长安');
  assert.equal(mapLabel('安条克 (今安塔基亚附近)'), '安条克');
});

test('audience notes retain historical caveats and remove internal-field clauses', () => {
  assert.equal(audienceNote('世纪与约数按 date_label 显示；1877 年仅为一说。', '默认说明'), '1877 年仅为一说。');
  assert.equal(audienceNote('source_ids 用于引用；viewport 自动调整。', '以史料判断联系。'), '以史料判断联系。');
  assert.equal(audienceNote('   ', '地图路线为示意。'), '地图路线为示意。');
  assert.equal(audienceNote('连线为交流方向示意。', '默认说明'), '连线为交流方向示意。');
});
