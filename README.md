# McTrail · 麦路同行

**Run. Ride. Refuel.**

一个可安装的 Agent Skill：规划跑步与骑行路线，把麦当劳作为沿途可选的休息、
补给或终点站。支持环线、点到点，关注夜跑/夜骑的预计到达时间与营业窗口。

**当前阶段：第一版 Skill 与本地计算器。** 高德实时路线、门店跨源匹配和真实夜间
营业信息尚待联调；不是已经验证过的导航产品，也不是麦当劳或高德官方产品。

## 能做什么

- 引导 Agent 使用高德实际步行/骑行路网规划候选，而不是拿直线凑里程。
- 串接麦当劳门店查询，核对地点身份与到访时间；未知营业信息明确保留未知。
- 用 Python 计算分段里程、预计时刻、跨午夜停留和营业窗口冲突。
- 输出路线卡片：里程、用时、补给站、来源、不确定项及有依据的地图入口。
- 第一版只读：不自动下单、领券、兑积分，也不读取用户账户地址或历史订单。

## 安装到 Copilot CLI

需要支持 Agent Skills/MCP 的宿主，以及 Python 3.10+。计算脚本仅使用标准库，
不需要 `pip install`。Skill 目录必须整体安装，不能只复制 `SKILL.md`。

克隆本仓库后，在仓库根目录运行（Windows PowerShell）：

```powershell
copilot skill add .\skills
copilot skill list
```

这会把整个 `skills` 目录注册为本机技能来源，不复制文件；请保留该克隆目录。
已经打开的 Copilot 会话执行 `/skills reload`，然后用 `/skills info mctrail` 查看状态。
也可以把整个 `skills\mctrail` 目录复制到个人目录 `%USERPROFILE%\.copilot\skills\mctrail`。

其他支持标准 Agent Skills 的宿主，按其官方文档安装同一个完整目录；
本仓库不声称已经在所有客户端实测兼容。

参考：[Copilot 安装 Skill](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)、
[Agent Skills 格式](https://agentskills.io/specification)。

## 配置两个 MCP

**安装 Skill 不等于安装或认证 MCP。** 实际路线需要：

| 服务 | 用途 | 凭据 |
|---|---|---|
| 高德地图 MCP | 地点解析、步行/骑行路网、地点搜索、地图入口 | 高德“Web 服务” Key |
| 麦当劳中国 MCP | 门店查询、时间；按需查询补给餐品 | 麦当劳 MCP Token |

`mcp-config.example.json` 是 **HTTP 类型的配置模板**，只含环境变量占位符。
不同客户端的类型名和变量展开规则不同：不要假定 `${...}` 会自动替换。
按宿主文档在仓库外的个人配置中注入真实值，或使用宿主的私密输入界面配置。
不要把真实配置保存到公开仓库；本项目不会自动修改、覆盖或启用用户的 MCP 设置。

高德 Key 在连接 URL 中，完整鉴权 URL 也必须当秘密处理。
Skill 不需要、更不应该让 Agent 读取凭据文件。Token/Key 不出现在聊天、分享卡片、
异常输出或示例中。

官方接入说明：
- [高德 MCP 与创建 Key](https://lbs.amap.com/api/mcp-server/create-project-and-key)
- [高德远程接入](https://lbs.amap.com/api/mcp-server/gettingstarted)
- [麦当劳 MCP](https://github.com/M-China/mcd-mcp-server)

## 使用

连接两个 MCP 后，在宿主中直接提出需求，例如：

> 用 McTrail 帮我从上海人民广场跑一条约 8 公里的环线，今晚 21 点出发，
> 六分配速，中途在麦当劳休息 10 分钟，最多 9 公里。

> 用 McTrail 规划从上海人民广场骑到徐家汇的路线，明天上午 10 点出发，
> 中途想在麦当劳停 15 分钟。先比较直接路线与带补给站的路线，不下单。

以上只是输入示例，**不是已查询或推荐的真实路线**。Agent 应确认具体点位与日期，
查到真实道路数据后才能输出路线；没有地图连接时应说明缺失，不凭常识生成路线。
夜间没有照明、通行或堂食证据时不能承诺“安全”或“可以进店休息”。

## 不用 Key 的计算演示

```powershell
python .\skills\mctrail\scripts\route_metrics.py .\skills\mctrail\examples\night-loop.json
```

这是**虚构数据**：8.2 公里、23:50 出发、00:14 到站，但计划休息到 00:29，
而关门时间是 00:20。脚本会报告 `closes_during_stop`，预计结束为次日 00:54:12。
它演示“到店时开门不等于整个停留都可用”，不能生成导航或证明接口已经打通。

真实数据请放仓库外的临时目录，或被忽略的 `.runtime` 目录。
完整输入契约见 [route-input.md](skills/mctrail/references/route-input.md)。

## 目录与协作

```text
skills\mctrail\
  SKILL.md                 触发条件、规划步骤与输出格式
  references\tools.md      两个 MCP 的职责、身份匹配与失败处理
  references\route-input.md 计算器 JSON 契约
  scripts\route_metrics.py 分段数字、时间和营业窗口计算
  examples\night-loop.json 明确标记的合成反例
tests\
  test_route_metrics.py    计算器行为测试
MCP_INTEGRATION.md         接入流程、业务价值与联调边界
mcp-config.example.json   无凭据模板
```

小伙伴可以分别负责路线/环线策略、门店与营业时间适配、Skill 交互与地图展示。
修改计算输入/输出时，同步更新 `route-input.md` 和调用示例，避免 Skill 与脚本脱节。
改动应小而完整，通过分支和 PR 协作，不把真实路线、账号数据或凭据放入 PR。

从仓库根目录运行：

```powershell
python -m unittest discover -s tests -v
```

补充现场案例时先去掉个人地址和账号信息；合成样例与真实查询结果必须分别标注。
后续联调重点是：步行/骑行真实返回结构、门店跨源身份、跨午夜营业时间、
完整路线地图入口，以及环线重叠/折返的识别与披露。

## 参赛准备与边界

本仓库尚未报名，也不代表已完成全部参赛条件。报名之前，由项目负责人阅读官方规则，
确认适用资格与授权，按官方原文加入 `CONTEST_DECLARATION.md`，完成真实 MCP 联调、
确认代码发布许可，再提交报名。当前不包含 WorkBuddy 开发记录，不声称满足专项奖励条件。

路线仅供出行前参考，实际路况、开放时间和门店服务以现场及官方信息为准。
不提供医疗、营养或专业运动建议，不承诺照明、路面、交通环境或服务可用性。
