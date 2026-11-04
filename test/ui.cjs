// Offline browser regression. Install Playwright separately; no university requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ timezoneId: 'Asia/Shanghai' });
    await page.clock.install({ time: new Date('2026-11-05T10:00:00+08:00') });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const data = JSON.parse(fs.readFileSync(path.join(root, 'docs/schedule-demo.json')));
    data.schedule.push({ ...data.schedule[0], KCDM: 'WEEKEND', KCMC: '周末示例课', XQ: '7' });
    const html = fs.readFileSync(path.join(root, 'templates/schedule.html'), 'utf8').replace('__DATA__', JSON.stringify(data));
    await page.route('**/*', route => route.request().url() === 'http://schedule.test/'
      ? route.fulfill({ contentType: 'text/html', body: html })
      : route.fulfill({ status: 200, body: '' }));
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 960 });
      await page.goto('http://schedule.test/');
      for (const week of ['before', '1', '9', '16', 'after']) {
        await page.selectOption('#weekSel', week);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        if (week !== '9') assert((await page.locator('#todayList').innerText()).trim());
      }
      await page.locator('#onlyToday').check({ force: true });
      assert.equal(await page.locator('#weekSel').inputValue(), '9');
      assert.equal(await page.locator('th.daycol').count(), 1);
      assert.equal(await page.locator('#gridKicker').innerText(), 'DAILY OVERVIEW');
      assert(await page.locator('#weekSel').isDisabled());
      const course = page.locator('.blk').first();
      assert(await course.evaluate(element => element.clientWidth) > 150);
      await course.focus();
      await page.keyboard.press('Enter');
      assert(await page.locator('#modalClose').evaluate(element => element === document.activeElement));
      for (const key of ['Tab', 'Shift+Tab', 'Tab']) {
        await page.keyboard.press(key);
        assert(await page.locator('#modalClose').evaluate(element => element === document.activeElement));
      }
      await page.keyboard.press('Escape');
      assert(await course.evaluate(element => element === document.activeElement));
      assert.equal(await page.locator('.wrap').evaluate(element => element.inert), false);
      await course.click();
      await page.locator('#modalClose').click();
      assert(await course.evaluate(element => element === document.activeElement));
      await page.locator('#onlyToday').uncheck({ force: true });
      assert.equal(await page.locator('th.daycol').count(), 5);
      assert.equal(await page.locator('#gridKicker').innerText(), 'WEEKLY OVERVIEW');
      assert.equal(await page.locator('#weekSel').isDisabled(), false);
      console.log('PASS ' + width + 'px: week/empty states, daily column, modal keyboard and focus return');
    }
    await page.clock.setFixedTime(new Date('2026-11-08T10:00:00+08:00'));
    await page.goto('http://schedule.test/');
    await page.locator('#onlyToday').check({ force: true });
    assert.match(await page.locator('.blk').innerText(), /周末示例课/);
    await page.evaluate(() => { DATA.schedule.length = 0; render(); });
    assert.match(await page.locator('#todayList').innerText(), /今天没有课程/);
    assert.deepEqual(errors, []);
    console.log('PASS weekend course, empty day and no browser errors');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
