# API与窗口使用说明

核对日期：2026-11-16。实际可用功能以当前窗口和账户为准。

## 不配置API：窗口路线

如果当前窗口有实际可调用的内置图片生成/编辑工具，可以直接使用，不需要用户配置OPENAI_API_KEY。受窗口的订阅、额度和功能限制，不等于无限免费；不能将其当作可以指定任意API模型、接口和参数的通道。原生GIF能力也以当前工具为准，先检查能力，不承诺精确帧数或节奏。

先用Skill分析素材并整理提示词，得到用户生成授权后再使用内置工具。若当前窗口不能生成，交付完整提示词和参考图清单，让用户在支持生图的窗口生成，再将原始PNG/GIF带回进行本地组帧、加字和验收。普通ChatGPT聊天不保证识别或安装Codex Skill；可以粘贴提示词和要求使用。窗口工具如有与本地Python处理不同的使用要求，遵守实际工具要求。

官方帮助目前说明：ChatGPT GIF功能正在逐步开放，不能直接编辑用户上传的动画GIF。因此参考GIF先在本地拆帧分析，再用角色图和动作说明生成新内容；不要承诺将原参考GIF上传就能直接替换角色。PNG关键姿态加本地组帧仍可使用。

## 配置API：Windows PowerShell

1. 在 https://platform.openai.com/api-keys 创建API密钥，妥善保存；确认项目账单和目标模型访问条件。权限使用最小所需：模型列表读取、所用图片端点请求。具体控制名称以后台实际界面为准。
2. 在本地PowerShell进入解压后的Skill目录，运行：

```powershell
powershell -NoProfile -File ".\scripts\set_api_key.ps1"
```

脚本仅在本地隐藏输入，写入当前Windows用户的OPENAI_API_KEY环境变量，不写入项目，不显示密钥。Windows用户环境变量不是加密保险库；共用电脑应改用自己的安全凭据方案。此设置会替换该用户已有的同名变量。新终端或重启Codex后可继承；不要将真实密钥写进聊天、脚本、截图或分享包。

3. 安装Python后，在新终端先做零网络dry-run：

```powershell
python ".\scripts\check_api.py"
```

只显示密钥是否存在，不发送请求。若显示不存在，重新打开应用/终端，检查是否在同一Windows用户下设置，不要打印变量内容。

4. 如需连通性检查，明确加参数：

```powershell
python ".\scripts\check_api.py" --check-models
```

此操作只请求官方 `GET /v1/models`，不发送图片生成请求，不产生图片生成费用。它会发送密钥到官方API用于认证。返回200仅证明此次模型列表可访问；模型可见不代表Images权限、GIF、透明背景或特定参数可用。

可选：检查指定模型是否列出（名称仅为用户选择，不作为支持承诺）：

```powershell
python ".\scripts\check_api.py" --check-models --model "你的目标模型名"
```

401/403/429或网络错误均只报告状态，不自动重试，不做付费探测。不要仅凭模型列表推断生成成功。

## 之后怎样生成

v5已内置 scripts/generate_api.py 图片编辑生成器、参数示例与批次账本。配置密钥不会自动开始生成。按 [api-runner.md](api-runner.md) 核对参数、准备自己的参考图和提示词、离线预览，提交请求上限与费用估算给用户确认后才执行。未授权不执行图片请求，不静默换模型。ChatGPT订阅与API计费分别管理。

离线GIF检查需要Pillow，可在自己的Python环境安装：`python -m pip install Pillow`。API检查脚本仅用Python标准库。

## 官方资料

- 窗口生图与批量API：https://learn.chatgpt.com/docs/image-generation
- ChatGPT图片功能：https://help.openai.com/en/articles/11084440-images-in-chatgpt
- API模型列表：https://developers.openai.com/api/reference/resources/models/methods/list
- API快速入门：https://developers.openai.com/api/docs/quickstart
