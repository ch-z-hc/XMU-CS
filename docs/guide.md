# 使用指南

[返回 README](../README.md)

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置

复制示例配置并填写账号：

```bash
cp config.example.json config.json
```

Windows 命令提示符中可用 `copy` 代替 `cp`。

`config.json` 含密码，已被 `.gitignore` 忽略，请勿提交到公开仓库。

如果教务接口没有返回学期首周日期，可以在配置中手动填写 `start_date`（格式 `YYYY-MM-DD`）。例如本学期下周一开学：

```json
{
  "term": "",
  "week": "",
  "start_date": "2026-09-07"
}
```

`start_date` 表示所选学期第 1 周的周一；填写后页面顶部会按该日期计算各周的日期范围，周课表表头也会显示每天对应的日期，并在打开页面时自动切换到当前周。切换 `term` 时请同步更新。留空时，如果接口也没有提供日期，则不显示日期范围和每天日期，也不会根据日期自动切换周次，避免使用错误的推算日期。

注意厦大的周次**从周日开始、周六结束**（校历里第一学期 2026-09-06 ~ 2027-01-09 正好是 18 个「周日→周六」，寒暑假也一样），而 `start_date` 填的是那一周里的周一。所以第 1 周 = 9/6(日) ~ 9/12(六)，周日算下一周的第一天（页面顶部的日期范围也按周日 ~ 周六显示）。

如果配置了 `week`，或运行时传入 `--week`，则以手动指定的周次为准，不进行自动切换。

在开学前，页面不会把尚未开始的课程误判为“今日课程”。

周次下拉框会在自动模式下额外显示“未开学”和“已放假”状态；选择这两个状态时显示空课表，并分别提示开学日期或学期结束。

也可以使用环境变量：

```text
XMU_USER=学号或工号
XMU_PASS=密码
```

命令行参数的优先级高于环境变量和 `config.json`。

## 使用

```bash
python fetch_schedule.py                         # 使用 config.json
python fetch_schedule.py --user X --password Y   # 直接指定账号密码
python fetch_schedule.py --week 3                # 查看第 3 周
python fetch_schedule.py --term 20252            # 指定学年学期代码
python fetch_schedule.py --no-open               # 生成但不打开浏览器
python fetch_schedule.py --out out/my.html       # 指定输出路径
```

运行后默认生成 `schedule.html`。该文件包含个人课表数据，默认被 `.gitignore` 忽略；如果要部署页面，请确认其中没有不希望公开的信息。

## 应用图标

页面已内置一套与界面配色一致的应用图标（蓝色渐变背景 + 日历课表卡片）：

- `assets/icon-192.png`：Android / Chrome 主屏图标
- `assets/icon-512.png`：PWA 及高分辨率图标
- `assets/apple-touch-icon.png`：iPhone / iPad「添加到主屏幕」图标
- `manifest.json`：主屏应用名称、启动方式和图标配置

修改设计后可重新生成所有图标：

```bash
python3 tools/make_icons.py
```

## 离线检查与界面维护

页面模板在 `templates/schedule.html`；修改后，生成的课表仍是单个 HTML 文件。模板必须与 Python 脚本一起保留。

```sh
node test/week.mjs
python test/build_html.py
python tools/build_demo.py
```

浏览器回归使用 Playwright：安装后运行 `node test/ui.cjs`，或通过 `PLAYWRIGHT_MODULE` 指定现有安装路径。CI 会检查 320 / 390 / 768 / 1440 像素视口、单日模式与弹窗键盘操作。所有课程均为模拟数据。

周次回归覆盖开学前、学期内、学期后及周日边界。演示页面由同一模板和 `docs/schedule-demo.json` 中的模拟数据生成，不读取个人配置或访问教务。

## 示例字体

公开示例使用 [霞鹜文楷](https://github.com/lxgw/LxgwWenKai) 和 [Maple Mono](https://github.com/subframe7536/maple-font)，分别用于中文和英文、数字。示例所需的 regular / bold 字体分片保存在 `docs/fonts/`，由 `docs/demo-fonts.css` 加载；普通生成页面仍使用模板的默认字体。

字体采用 SIL OFL 1.1，文楷 webfont 打包采用 MIT 许可，许可文件位于 `docs/fonts/`。这些分片覆盖当前模拟数据和界面文字；若新增示例文字，需要检查对应字形是否包含在内。截图前等待 `document.fonts.ready`，避免截到回退字体。

## 工作原理

脚本使用 Python `requests.Session` 模拟 HTTP 会话：

1. 请求 CAS 登录页，读取动态参数。
2. 按前端规则使用 `AES-128-CBC / PKCS7` 加密密码并提交登录表单。
3. 跟随门户重定向，使用 CAS Ticket 获取教务微应用会话。
4. 调用教务接口，拉取学期、周次、节次、学生信息和完整学期课表。
5. 将前端实际需要的数据内嵌到单文件 HTML 中。

课表接口不传 `ZC` 参数，而是拉取完整学期课程，再由前端根据 `ZCBH` 周次掩码过滤，因此可以正常切换周次。

## 安全说明

- 不要提交 `config.json`、`schedule.html` 或包含真实账号信息的文件。
- 生成 HTML 会包含姓名、课程、教师和教室；公开部署前请先检查内容。
- 登录仅用于本人课表查询，请在合法合规范围内使用。
