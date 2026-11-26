# UI 改版设计稿（参考用，不是可运行代码）

在线画布（需登录 claude.ai，可点击浏览）：https://claude.ai/artifact/CLfL572Tb3GawhsKGwhhmM

本目录是画布上每张画板的源文件，供开发时对照布局、文案和交互。实现以 `docs/specs/ui_redesign.md` 为准。

## 怎么读 `.dc.html`

这些文件依赖画布的运行时（`./support.js`），**不能直接用浏览器打开**。阅读方式：

- `<x-dc>` 里的 HTML 是界面结构，内联 `style` 是视觉规格（颜色、间距、字号）。
- `{{name}}` 是占位，值来自文件末尾 `<script type="text/x-dc">` 里 `renderVals()` 返回的对象。
- `<sc-for list="{{xs}}" as="x">` 是循环，`<sc-if value="{{cond}}">` 是条件分支。
- `renderVals()` 里的数据都是**示意数据**（时长、版本号、序列号、trial 数），不要当作真实值。
- `TaskWindow.dc.html` 的脚本里有一个可参考的选区试算逻辑（按最大空闲合并 trial、加前后保留、裁剪到记录范围）。真实实现必须调用 `core/segments.py` 的 `select_task_windows`，不要照抄示意逻辑。

## 画板与页面对应

| 文件 | 页面 | 期次 |
|---|---|---|
| `Main.dc.html` | Session 列表（首页） | P1 |
| `WizardData.dc.html` | 新建 ①：数据与发现结果卡 | 发现结果卡 P0，向导外壳 P1 |
| `WizardSubject.dc.html` | 新建 ②：动物与探针 | P1 |
| `WizardParams.dc.html` | 新建 ③：参数（预设、差异、搜索） | 预设与差异 P0，搜索与分级 P2 |
| `WizardReview.dc.html` | 新建 ④：运行前检查与运行方式 | P1 |
| `TaskWindow.dc.html` | 任务时段：预览、调参、应用、确认 | P1 |
| `Workspace.dc.html` | Session 工作区（运行中） | P1 |
| `RerunConfirm.dc.html` | 从此阶段重跑：确认弹窗 | P0 |
| `ErrorState.dc.html` | 阶段失败：原因与建议 | P1 |

`canvas.json` 是画布的布局索引，开发时可忽略。

## 视觉规格速查

- 字体：Inter + Noto Sans SC；路径、参数键名、日志用 JetBrains Mono。
- 底色 `#F6F6F3`，卡片 `#FFFFFF`，边框 `#E3E3DE`，正文 `#15171C`，次要文字 `#5B606B`。
- 强调色 `#0B6E8E`（每屏只有一个主按钮用它）。
- 状态：完成 `#2E8B57`/底 `#E4F2E9`，运行中 `#0B6E8E`/底 `#E3F0F5`，待确认 `#D99A1E`/底 `#FBF0DA`，失败 `#C8372D`/底 `#FBE6E4`。
- 时间轴沿用现有配色：原始 `#A6AFB7`，已保存 `#2777AB`，试算 `#DB852C`，有刺激 trial `#26967C`。
