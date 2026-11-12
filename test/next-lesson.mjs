import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const template = readFileSync(new URL('../templates/schedule.html', import.meta.url), 'utf8');
const data = JSON.parse(readFileSync(new URL('../docs/schedule-demo.json', import.meta.url)));
const functions = ['fmt', 'activeWeek', 'weekDate', 'nextLesson'].map(name=>
  template.match(new RegExp('function '+name+'\\([\\s\\S]*?\\n\\}'))[0]
).join('\n');
const context = { DATA: data };
runInNewContext(functions+'\nthis.findNext = nextLesson;', context);
const find = time=>context.findNext(new Date(time));

assert.equal(find('2026-11-05T10:00:00').c.KCDM, 'DEMO07');
assert.equal(find('2026-11-05T11:00:00').c.KCDM, 'DEMO07');
assert.equal(find('2026-11-05T11:50:00').c.KCDM, 'DEMO07');
assert.equal(find('2026-11-05T11:50:00.001').c.KCDM, 'DEMO08');
assert.equal(find('2026-11-05T20:50:00.001').c.KCDM, 'DEMO09');
const fallback = find('2026-11-06T12:00:00');
assert.equal(fallback.c.KCDM, 'DEMO10');
assert.equal(fallback.startTime, '16:40');
assert.equal(fallback.endTime, '18:20');
assert.equal(find('2026-11-07T12:00:00').start.getDate(), 9);
assert.equal(find('2026-09-01T00:00:00').start.getDate(), 7);
assert.equal(find('2027-01-01T00:00:00'), null);

// A Sunday in week 10 precedes that week's Monday; inactive weeks are skipped.
data.schedule.push({ ...data.schedule[0], KCDM: 'SUNDAY', XQ: 7, ZCBH: '0000000001000000' });
assert.equal(find('2026-11-07T12:00:00').c.KCDM, 'SUNDAY');
assert.equal(find('2026-11-07T12:00:00').start.getDate(), 8);
assert.equal(find('2026-10-31T12:00:00').start.getDate(), 2);
data.schedule.reverse();
assert.equal(find('2026-11-05T10:00:00').c.KCDM, 'DEMO07');
data.schedule.length = 0;
assert.equal(find('2026-11-05T10:00:00'), null);
console.log('PASS next lesson: inclusive end, in-progress, next day/week, Sunday, inactive weeks, period fallback, empty term and ordering');
