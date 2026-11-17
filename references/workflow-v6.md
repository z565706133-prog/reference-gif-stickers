# v6：让使用者按实际制作步骤操作

使用者负责提供素材、确认整批生成方案、审核第一张与后续批次。Codex负责读取本说明，运行本地工具，查看联系表及动画、写动作分析和提示词、按授权调度生成、修复与交付。不要把下面的命令清单全部抛给普通用户；自行执行已授权的本地步骤。

## 环境与项目

Python 3.10+、Pillow和用户有权使用的中文字体即可。无需Git、FFmpeg、显卡或CUDA。缺Pillow时协助安装 `python -m pip install Pillow`，不要静默改系统设置。先doctor检查，再执行其他步骤。

```powershell
python scripts/sticker_workflow.py doctor --font "用户字体.ttf"
python scripts/sticker_workflow.py init "新项目目录" --character "角色.png" --references "参考GIF目录" --font "用户字体.ttf"
python scripts/sticker_workflow.py extract "新项目目录"
python scripts/sticker_workflow.py status "新项目目录"
```

init复制原图及原参考，不改输入；新项目路径必须不存在。project.json保存任务状态、角色哈希、字体和选中版本。默认输出240×240、白边3px、500000字节上限。后续续作先status，不重新init。项目状态与历史文件一起保存；API账本保留在自己的批次配置旁。

## 分析与生成方案

每个任务在 `tasks/R001/analysis/` 获得全部RGBA帧、contact.png、metadata.json与motion-analysis.json。Codex逐张打开完整联系表，必要时查看源GIF/单帧，填写动作、情绪、构图、遮挡、文字出现时段、需补画区域。不能只看首帧或把null模板当作已分析。联系表展示不了运动连续性时要检查动画。

由Codex逐张推荐路线并写出理由：PNG关键姿态或支持时的直接GIF。不是按帧数一刀切。将逐帧时长、关键姿态、路线、完整提示词、每张及全批上限、费用依据整理成批次方案。新角色先做一张；已通过第一张直接复用风格参数，不反复审批。

提示词结构：用户的角色不变量与画风→本张情绪→目标帧的具体姿态、视线和道具→参考构图及自然遮挡→背景及无字要求→输出形式。缺少视角或姿态时先说明；仅在授权明确包含时补图。纯色平涂可减少细碎色调噪点，但不擅改已确认风格。

API路线使用api-runner.md；窗口路线使用实际内置工具，保存原始输出，不虚构API账单。授权计数只针对相应生成通道，不混用窗口额度和API额度。

## PNG与GIF接入

PNG路线：保存原始生成图到任务inputs下，Codex把 `render.json` 的frames填写为相对任务目录的路径，顺序与每个参考时间槽一一对应；同一PNG可重复引用来保留停顿。人物源画布需同尺寸，禁止独立紧裁各帧后缩放。缺姿态不能靠重复一张蒙混通过。

GIF路线：先检查模型实际输出。源文件保留，接入工具只接受帧数与逐帧时长已匹配的文件；不匹配时先分析，并按用户已授权范围另存本地修正版，再导入，不能以导入名义悄悄改变节奏。

```powershell
python scripts/sticker_workflow.py import-gif "项目" --task R001 --source "生成结果.gif" --name imported-v1
```

## 免费处理与白边

`render.json`设置：

- frames、durations_ms：路径映射和参考完整时长数组；程序严格核对参考节奏，不平均化。
- union_crop：默认true，计算所有帧联合alpha包围盒，使用统一缩放、中心与底部位置；不把自然局部动作当抖动消掉。
- character_box：最终240px中留给人物的区域，默认[10,54,230,230]。参考为半身、入画或裁切时Codex先按参考安排源画布/遮罩，再检查构图，不自动缩全身。
- outline_px：**默认最终240×240画布3px白色贴纸描边**。4倍画布外扩后统一缩小；用户可调宽度或设0关闭。已有描边的素材避免重复扩边，优先选无描边动作母版。
- caption、font、font_size、text_top、text_stroke：固定中文位置、字体、字号及文字白边；不把每帧单独自动居中。文字需目视核对缺字；程序仅验证字体可加载和布局范围，不能证明字体许可或所有字形完整。
- background_remove：默认null（不抠背景），明确启用例：`{"rgb":[255,255,255],"tolerance":18}`。只清理外部连通的近背景像素，保护封闭内部浅色；内部与背景相连、边界不明确时仍可能误删，必须配protection_masks并目视核对，不能声称万能精确抠图。
- protection_masks：可选，每帧对应一张同尺寸灰度保护蒙版（白色区域不移除）。复杂抠图或遮挡先由Codex免费做局部蒙版/图层处理，再交给合成器。
- source_alpha_floor：默认0，不动原alpha；诊断确认低alpha背景残留后才可另存对照尝试阈值。过高会损失细边，不能作为通用去毛边开关。
- alpha_threshold：最终GIF二值透明阈值默认128。导出同时保留RGBA帧与半透明APNG诊断，调参需对照深浅背景；不能把APNG的平滑当成GIF已解决。

程序使用预乘alpha缩放、所有帧共用调色板、不自动降帧或降色，GIF完整保留相同连续帧的时间槽。若超过大小目标，technical_pass=false，先优化，不悄悄牺牲画质。边缘诊断顺序见production.md。

```powershell
python scripts/sticker_workflow.py render "项目" --task R001 --revision v1
python scripts/sticker_workflow.py review "项目"
```

每次render必须新版本名。保存PNG母帧、GIF、APNG诊断、深浅静态对照和validation.json。审核页可切换深浅背景同时播放。手臂连接、道具刚体长度、独立眨眼、坐姿转换等没有通用自动修复按钮；Codex先看图诊断，再免费编写/应用局部修复并保留层文件，确实不能解决才按授权补画。禁止将这一步描述成全自动视觉修复。

## 第一张和批次审核

Codex先检查视觉：角色不变量、道具形状色彩、手臂结构、文字、尺度、边缘和循环。技术通过不自动变用户通过。得到用户真实审核决定后记录：

```powershell
python scripts/sticker_workflow.py decision "项目" --task R001 --status approved --user-instruction "真实用户通过原文"
```

未通过保留pending_review，修改新revision；取消用cancelled。修改后status自动回到pending_review，不继承旧版本通过。decision记录选中版本与哈希。不得拿演练的通过记录当用户对真实成品的批准。

## 投稿打包

所有入选作品通过后，填写project.json的listing（专辑名称、介绍、作者名、版权信息）；母版如需头部图标可设icon_crop为母版紧裁后的[x0,y0,x1,y1]，并目视检查。否则生成全身图标候选，不假称其小尺寸可读性已合格。

```powershell
python scripts/sticker_workflow.py package "项目" --name submission-v1
```

仅导出approved的当前版本，逐字节复制GIF，不包括取消和待审核作品。生成无字透明240封面、50图标、750×400不透明无字横幅候选、文案、哈希清单和ZIP。候选布局是起点，Codex应按项目实际免费排版后给用户看，不以默认布局代替设计审核。当前官方数量及尺寸等规则、字体素材权利和实名信息仍需实际核实；程序始终标记未提交、官方规则未核实。用户说已上传时记为用户报告，不冒称后台已观察。

## 技术边界与恢复

CLI是本地单操作者工作流，避免两进程同时改同一project.json；API生成器另有并发锁。断点先读status、events、selected_revision和API账本，保留原始输出。禁止删记录重置调用额度。代码使用Pillow私有GIF写入接口以保留精确时间槽，升级Pillow后先运行test_sticker_workflow.py验证兼容性，不默默回退到会合并帧的写法。
