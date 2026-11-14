import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {auditDirector} from '../src/directorData';
import type {DirectorSceneData} from '../src/directorTypes';

const args = process.argv.slice(2);
const value = (flag: string) => args[args.indexOf(flag) + 1];
const input = args.includes('--props') ? value('--props') : args[0];
const output = args.includes('--output') ? value('--output') : args[1];
if (!input || !output) throw new Error('Usage: npx tsx tools/check-director.ts --props props.json --output report.json');
const source = fs.readFileSync(path.resolve(input));
const props = JSON.parse(source.toString('utf8'));
const director = (props.director ?? props) as DirectorSceneData;
const report = auditDirector(director, props.metadata?.fps ?? director.fps,props.metadata?.width??1280,props.metadata?.height??720,props.metadata?.playback_speed??1.15);
fs.mkdirSync(path.dirname(path.resolve(output)), {recursive: true});
fs.writeFileSync(path.resolve(output), JSON.stringify({...report,props_sha256:createHash('sha256').update(source).digest('hex')}, null, 2));
process.stdout.write(JSON.stringify({passed:report.passed,scene_id: report.scene_id, frame_count: report.frame_count, maximum_visible_groups: report.maximum_visible_groups, unconsumed_actions: report.unconsumed_actions, issues: report.issues.length, output: path.resolve(output)})+'\n');
if (!report.passed) process.exitCode = 1;
