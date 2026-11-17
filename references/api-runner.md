# 可执行API生成与批次记账（v5）

入口为 `scripts/generate_api.py`，仅使用官方 `POST https://api.openai.com/v1/images/edits`。改编自本项目已实际运行的单请求与批次程序，移除个人路径、角色设定和历史授权。需要 Python 3.10+、Pillow；网络使用标准库，不需要OpenAI SDK。只从环境读取密钥。

## 开始使用

1. 复制 `examples/batch.example.json` 到自己的项目目录，放入 `character.png` 和 `pose-01.txt`（完整无字动作提示词）。若需要多张参考，将本地文件路径列入images。提供多张姿态时每个job写自己的提示词和参数。
2. 示例默认 `parameters_verified=false`，因此不会误执行。先核对当前官方文档、账户权限、目标模型和尺寸，再填写 `verified_on`，将该字段设为true。此字段是人工核实声明，程序不会假装离线验证了模型权限。支持字段采用明确白名单，不支持就停止，不静默修改。
3. 示例PNG参数来自本项目实际用法：Sunburst、1024×1024、high、complexity=medium、透明PNG、n=1。它不是对所有账户的可用性保证。GIF可设 `output_format=gif`、`size=512x512`、`background=auto`、`frame_count=3`、`frame_duration_ms=100`，但必须单独核实当前模型GIF预览访问及参数。官方文档核对于2026-11-16，GIF帧数支持2～16，时长按10ms编码；原生透明效果须检查真实alpha，不靠提示词保证。
4. 可配置 `pricing`：`text_input_per_million`、`image_input_per_million`、`output_per_million`（USD/百万token）、`source`、`verified_on`。三档单价须与目标模型实际计费一致；如模型输出计费不适合此公式，留空并按账单核对，不能硬算。未填价格或usage不完整时费用为null，绝不记成免费。

从Skill目录执行（将项目路径替换成自己的）：

```powershell
# 离线预览：显示完整提示词、参考哈希、参数及上限，不消耗额度、不联网
python scripts/generate_api.py "你的项目/batch.json"

# 仅在用户已明确批准之后，记录真实授权原文；此命令不发请求
python scripts/generate_api.py "你的项目/batch.json" --approve "用户的真实批次授权原文"

# 付费入口：明确执行指定job，只发一次请求；本次技能升级禁止运行这一步
python scripts/generate_api.py "你的项目/batch.json" --execute pose-01

# 本地账本：已占用次数、成功/错误、用量、已知估算与未知费用次数
python scripts/generate_api.py "你的项目/batch.json" --report
```

设置密钥按setup.md执行。配置密钥不等于授权生成。Codex不得自行编造授权原文，用户只说检查或免费时禁止记录生成批准或执行付费入口。

## 上限与中断

- 一个job对应一个明确姿态/补画请求描述，`cap`为它的上限；`total_cap`为整个批次上限。每次调用n=1，不自动遍历整批，不自动重试。批次执行可以由Codex逐次调度，但每次检查结果，成功后不无故再抽卡。
- 原始配置、所有提示词、输入文件内容哈希均绑定审批。修改模型、参数、提示词、单张上限或总上限后，原批准失效。新姿态依赖尚未生成文件时，先完成并审核前一步，再用实际输入准备后续方案；不得对不存在的文件虚构哈希。
- 全批锁覆盖检查、预留和网络请求，防止并发超额。输出目录固定为配置旁的 `runs-批次ID`。同一批次必须继续使用同一配置位置和ID，不通过复制配置/更名/删记录重置配额。
- 发送前永久写attempt记录；HTTP错误、未知网络结果和输出不符均停止整个批次。它们可能已收费，不把失败当零次。崩溃留下的锁和未完成记录需人工核对，不能删掉后重发。需要继续必须新的真实授权并引用旧批次账本，不能当作免费重试。
- 保存request.json（无密钥）、原始成功response.json、raw.bin及PNG/GIF、result.json。响应解码失败仍保留原始响应以供诊断，不再请求一次。报告记录usage和估算，`invoice_verified=false`。
- 输出检查记录实际帧数、时长、尺寸、loop、透明情况。输出可成功返回但未满足提示词；仍需视觉和技术验收，失败不自动调用模型修复。

## 费用说明

请求次数上限不是硬性金额上限。生成前先核对官方价格，给出场景估算或未知说明。响应后以实际usage计算已知估算，账单未核对不能声称实际扣费。HTTP错误/中断费用未知，保留待核对项。PNG与GIF如适用不同价目，应分成不同批次配置。

官方参数文档：https://developers.openai.com/api/reference/resources/images/methods/edit
