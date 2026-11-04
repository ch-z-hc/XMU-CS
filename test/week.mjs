import { readFileSync } from 'fs';
const src = readFileSync(new URL('../templates/schedule.html', import.meta.url), 'utf8');
// 从模板里把那四个日期/周次函数抠出来
const names = ['weekRangeLabel', 'currentWeekNumber', 'isToday', 'weekDate'];
let code = '';
for (const n of names) {
  const m = src.match(new RegExp('function ' + n + '\\([\\s\\S]*?\\n\\}', 'm'));
  if (!m) throw new Error('没找到函数 ' + n);
  code += m[0] + '\n';
}
let NOW = null;
const harness = `
const DATA = { term: { startDate: __START__ }, weeks: __WEEKS__ };
const dnum = d => (d.getMonth()+1) + '/' + d.getDate();
`;
const nowClass = `
class FakeDate extends Date {
  constructor(...a) { super(...(a.length ? a : NOW_ARG)); }
}
globalThis.Date = FakeDate;
`;
const mod = `
const NOW_ARG = NOW_VALUE;
${nowClass}
${harness.replace('__START__', "'2026-09-07'").replace('__WEEKS__', '[...Array(18)].map((_,i)=>i+1)')}
${code}
globalThis.__fns = { weekRangeLabel, currentWeekNumber, isToday, weekDate, dnum };
`;
const { runInNewContext } = await import('vm');
const ctx = { NOW_VALUE: null, console };
// 每个日期单独建一个上下文，注入“今天”
function fnsFor(iso) {
  const c = { NOW_VALUE: [`${iso}T12:00:00`], console };
  runInNewContext(mod, c);
  return c.__fns;
}
// 真值：教务的周次 —— 第 1 周从 2026-09-06(周日) 开始，周日 ~ 周六为一周
const SUN0 = new Date('2026-09-06T00:00:00');
const MON0 = new Date('2026-09-07T00:00:00');
const pad = n => String(n).padStart(2, '0');
const p = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());  // 按本地日期，别用 UTC
function truthWeek(d) {
  const days = Math.round((d - SUN0) / 86400000);
  if (days < 0) return 'before';
  const w = Math.floor(days / 7) + 1;
  return w > 18 ? 'after' : w;
}
let bad = 0, checked = 0;
for (let i = -6; i < 7 * 20; i++) {
  const d = new Date(SUN0.getTime() + i * 86400000);
  const iso = p(d);
  const f = fnsFor(iso);
  const want = truthWeek(d);
  const got = f.currentWeekNumber();
  checked++;
  if (String(got) !== String(want)) { bad++; console.log(`✗ 当前周 ${iso}: 页面给 ${got}，教务应为 ${want}`); continue; }
  // 每天日期标签：xq 1..7 都要落在教务那一周之内
  if (typeof want === 'number') {
    const got7 = f.weekDate(want, 7), got1 = f.weekDate(want, 1), got6 = f.weekDate(want, 6);
    const exp7 = p(new Date(MON0.getTime() + (want - 1) * 7 * 86400000 - 86400000));
    const exp1 = p(new Date(MON0.getTime() + (want - 1) * 7 * 86400000));
    const exp6 = p(new Date(MON0.getTime() + (want - 1) * 7 * 86400000 + 5 * 86400000));
    if (p(got7) !== exp7 || p(got1) !== exp1 || p(got6) !== exp6) {
      bad++; console.log(`✗ 第${want}周 日期标签 周日${p(got7)}(应${exp7}) 周一${p(got1)}(应${exp1}) 周六${p(got6)}(应${exp6})`);
    }
    // isToday：只有 xq 对应今天的那一格该为 true
    const xqToday = d.getDay() === 0 ? 7 : d.getDay();
    for (let xq = 1; xq <= 7; xq++) {
      const wantToday = xq === xqToday;
      if (f.isToday(String(xq), want) !== wantToday) { bad++; console.log(`✗ isToday(${xq}, 第${want}周) @${iso} = ${f.isToday(String(xq), want)}，应为 ${wantToday}`); }
    }
    // 范围标签应当以周日开头、周六结束
    const label = f.weekRangeLabel(want);
    if (want >= 2) {
      const l7 = `${(got7.getMonth()+1)} 月 ${got7.getDate()} 日`, r6 = `${(got6.getMonth()+1)} 月 ${got6.getDate()} 日`;
      if (!label.includes(l7) || !label.includes(r6)) { bad++; console.log(`✗ 第${want}周范围标签「${label}」不含 ${l7} / ${r6}`); }
    }
  }
}
console.log(`\n共验 ${checked} 个日期（开学前 6 天 ~ 第 20 周），失败 ${bad} 项`);
console.log('今天(2026-09-20 周日) 页面会选中的周次 =', fnsFor('2026-09-20').currentWeekNumber(),
            '| 范围 =', fnsFor('2026-09-20').weekRangeLabel(fnsFor('2026-09-20').currentWeekNumber()));
console.log('明天(2026-09-21 周一) 页面会选中的周次 =', fnsFor('2026-09-21').currentWeekNumber(),
            '| 范围 =', fnsFor('2026-09-21').weekRangeLabel(3));

if (bad) process.exitCode = 1;
