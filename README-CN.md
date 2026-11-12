<!-- mcp-name: io.github.vmware-skills/vmware-nsx -->

# VMware-NSX

<a id="readme-overview"></a>

通过专业工具调查和管理 VMware NSX 网络。

[English](https://github.com/vmware-skills/VMware-NSX/blob/main/README.md) · 简体中文

社区维护 · MIT 开源 · 非 VMware/Broadcom 官方产品。

[![18 秒调查示意演示](https://raw.githubusercontent.com/vmware-skills/marketplace/main/assets/demos/vmware-skills-zh.gif)](https://github.com/vmware-skills/marketplace/releases/download/demos-2026-11-12/vmware-skills-zh.mp4)

GIF 使用合成数据；视频包含脱敏的历史截图。[下载家族 AI 配音介绍（约 2 分钟）](https://github.com/vmware-skills/marketplace/releases/download/demos-2026-11-12/vmware-skills-zh.mp4)

<a id="readme-capabilities-and-workflows"></a>

## 能解决什么问题？

- 处理网段、网关、NAT 与 IP 地址池。
- 检查 BGP、路由与 Fabric 健康。
- 让配置操作明确且可审计。

<a id="readme-quick-start"></a>

## 快速开始

安装已发布 CLI，并查看可用命令：

```sh
uv tool install vmware-nsx-mgmt==1.15.3
vmware-nsx --help
```

需要 uv 与 Python >=3.10。远程查询前，在本地配置目标与凭据。[配置指南](https://github.com/vmware-skills/VMware-NSX/blob/main/skills/vmware-nsx/references/setup-guide.md)。

Agent 宿主安装见本模块的[配置指南](https://github.com/vmware-skills/VMware-NSX/blob/main/skills/vmware-nsx/references/setup-guide.md)，以及 [Cursor、Codex、Gemini CLI、Cline 与本地模型示例](https://github.com/vmware-skills/marketplace/blob/main/docs/agent-hosts-CN.md)。

<a id="readme-safety-and-audit"></a>

## 使用边界

包含网络配置写操作。NSX 权限与本地 Policy 继续生效；破坏性操作确认门不替代独立授权。

<a id="readme-mcp-configuration"></a> <a id="readme-troubleshooting"></a> <a id="readme-reference"></a>

## 详细文档

- [能力范围](https://github.com/vmware-skills/VMware-NSX/blob/main/skills/vmware-nsx/references/capabilities.md)
- [CLI 用法](https://github.com/vmware-skills/VMware-NSX/blob/main/skills/vmware-nsx/references/cli-reference.md)
- [Agent 使用约束](https://github.com/vmware-skills/VMware-NSX/blob/main/skills/vmware-nsx/references/agent-guardrails.md)
- [详细用法与架构](https://github.com/vmware-skills/VMware-NSX/blob/main/skills/vmware-nsx/references/detailed-guide-CN.md)
- [MCP 启动配置](https://github.com/vmware-skills/VMware-NSX/blob/main/.mcp.json)
- [唯一技能指令正本](https://github.com/vmware-skills/VMware-NSX/blob/main/skills/vmware-nsx/SKILL.md)

<a id="readme-companion-skills"></a>

属于 [VMware Skills 家族](https://github.com/vmware-skills/marketplace/blob/main/README-CN.md)：15 个 skill、14 个 MCP server 与一个共享 Policy 库。如果对你有用，欢迎 Star 家族门户。

<a id="readme-license"></a>

[问题与反馈](https://github.com/vmware-skills/VMware-NSX/issues) · [MIT](https://opensource.org/license/mit/)
