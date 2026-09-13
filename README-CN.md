<!-- mcp-name: io.github.vmware-skills/vmware-nsx -->
# VMware NSX

> **作者**: Wei Zhou, VMware by Broadcom — wei-wz.zhou@broadcom.com
> 本项目由 VMware 工程师维护的社区项目，非 VMware 官方产品。
> VMware 官方开发者工具请访问 [developer.broadcom.com](https://developer.broadcom.com)。

[English](README.md) | [中文](README-CN.md)

VMware NSX 网络管理：Segment、网关、NAT、路由、IPAM — 33 个 MCP 工具，领域专注。

> 基于 NSX Policy API，支持 NSX-T 3.0+ 和 NSX 4.x。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 伴生 Skills

| Skill | 范围 | 工具数 | 安装 |
|-------|------|:-----:|------|
| **[vmware-aiops](https://github.com/vmware-skills/VMware-AIops)** ⭐ 入口 | VM 生命周期、部署、Guest Ops、集群 | 49 | `uv tool install vmware-aiops` |
| **[vmware-monitor](https://github.com/vmware-skills/VMware-Monitor)** | 只读监控、告警、事件、VM 信息 | 27 | `uv tool install vmware-monitor` |
| **[vmware-storage](https://github.com/vmware-skills/VMware-Storage)** | 数据存储、iSCSI、vSAN | 11 | `uv tool install vmware-storage` |
| **[vmware-vks](https://github.com/vmware-skills/VMware-VKS)** | Tanzu 命名空间、TKC 集群生命周期 | 20 | `uv tool install vmware-vks` |
| **[vmware-nsx-security](https://github.com/vmware-skills/VMware-NSX-Security)** | DFW 微分段、安全组、Traceflow | 21 | `uv tool install vmware-nsx-security` |
| **[vmware-aria](https://github.com/vmware-skills/VMware-Aria)** | Aria Ops 指标、告警、容量规划 | 28 | `uv tool install vmware-aria` |
| **[vmware-avi](https://github.com/vmware-skills/VMware-AVI)** | AVI/NSX ALB 负载均衡、AKO | 28 | `uv tool install vmware-avi` |
| **[vmware-harden](https://github.com/vmware-skills/VMware-Harden)** | 合规基线、Drift 检测 | 6 | `uv tool install vmware-harden` |

## 快速安装

```bash
# 通过 PyPI
uv tool install vmware-nsx-mgmt

# 或 pip
pip install vmware-nsx-mgmt
```

### 离线 / 气隙环境安装（从源码）

本项目采用现代 PEP 517 构建系统（hatchling），因此**没有 `setup.py`**——这是设计
使然，不是文件缺失。如果你克隆源码后遇到 `ERROR: File "setup.py" or "setup.cfg" not
found ... editable mode currently requires a setuptools-based build`，说明你的 `pip`
版本低于 21.3，无法对非 setuptools 后端做*可编辑*（`-e`）安装。可编辑模式只是开发
便利，运行本工具并不需要它——任选其一：

```bash
# 在源码目录下——普通（非可编辑）安装会构建 wheel：
pip install .              # 不是  pip install -e .

# ……或先升级 pip，可编辑安装也能用：
pip install --upgrade pip && pip install -e .
```

对于**完全气隙的主机**，在联网机器上构建 wheel 再拷贝过去——目标机无需联网：

```bash
# 在联网机器上，把本包及其依赖收集为 wheel：
pip wheel . -w dist        # → dist/*.whl  （或：uv build，仅构建本包）

# 把 dist/ 拷到气隙主机，离线安装：
pip install --no-index --find-links dist vmware-nsx-mgmt
```

## 配置

```bash
mkdir -p ~/.vmware-nsx
cp config.example.yaml ~/.vmware-nsx/config.yaml
# 编辑 config.yaml，填入 NSX Manager 地址和用户名

echo "VMWARE_NSX_NSX_PROD_PASSWORD=your_password" > ~/.vmware-nsx/.env
chmod 600 ~/.vmware-nsx/.env

# 验证环境
vmware-nsx doctor
```

### config.yaml 示例

```yaml
default_target: nsx-prod
targets:
  nsx-prod:
    host: nsx-mgr.example.com    # NSX Manager IP 或集群 VIP
    username: admin
  nsx-lab:
    host: 10.0.0.100
    username: admin
```

密码不写在 config.yaml 里，按目标名从环境变量读取（`nsx-prod` →
`VMWARE_NSX_NSX_PROD_PASSWORD`，`nsx-lab` → `VMWARE_NSX_NSX_LAB_PASSWORD`），
或放进 `~/.vmware-nsx/.env`。上面的 `username` 同样可以被
`VMWARE_NSX_NSX_PROD_USERNAME` / `VMWARE_NSX_NSX_LAB_USERNAME` 覆盖，
两者在每次连接时一起读取，便于从密钥管理系统整对轮换。

## 功能概览

| 类别 | 工具 | 数量 | 读 / 写 |
|------|------|:----:|:------:|
| **Segment** | 列表、详情、创建、更新、删除 | 5 | 2 读 / 3 写 |
| **Tier-0 网关** | 列表、详情、BGP 邻居、配置 BGP | 4 | 3 读 / 1 写 |
| **Tier-1 网关** | 列表、详情、创建、更新、删除 | 5 | 2 读 / 3 写 |
| **NAT** | 列表、创建、删除 | 3 | 1 读 / 2 写 |
| **静态路由** | 列表、创建、删除 | 3 | 1 读 / 2 写 |
| **IP 池** | 列表、使用情况、创建池、删除池 | 4 | 2 读 / 2 写 |
| **Fabric 清单** | 传输区域、传输节点、Edge 集群 | 3 | 3 读 / 0 写 |
| **健康与排障** | 告警、传输节点状态、Edge 集群状态、Manager 状态、逻辑端口状态、VM 所在 Segment | 6 | 6 读 / 0 写 |

**合计**：33 个工具（20 只读 + 13 写）

## MCP 工具（33 个 —— 20 读 / 13 写）

| 类别 | 工具 | 类型 |
|------|------|------|
| Segment | `list_segments`、`get_segment`、`create_segment`、`update_segment`、`delete_segment` | 读/写 |
| Tier-0 网关 | `list_tier0_gateways`、`get_tier0_gateway`、`get_bgp_neighbors`、`configure_tier0_bgp` | 读/写 |
| Tier-1 网关 | `list_tier1_gateways`、`get_tier1_gateway`、`create_tier1_gateway`、`update_tier1_gateway`、`delete_tier1_gateway` | 读/写 |
| NAT | `list_nat_rules`、`create_nat_rule`、`delete_nat_rule` | 读/写 |
| 静态路由 | `list_static_routes`、`create_static_route`、`delete_static_route` | 读/写 |
| IP 池 | `list_ip_pools`、`get_ip_pool_usage`、`create_ip_pool`、`delete_ip_pool` | 读/写 |
| Fabric 清单 | `list_transport_zones`、`list_transport_nodes`、`list_edge_clusters` | 只读 |
| 健康 | `list_nsx_alarms`（按单一 severity 精确过滤）、`get_transport_node_status`、`get_edge_cluster_status`、`get_nsx_manager_status` | 只读 |
| 排障 | `get_logical_port_status`（按 Segment 查看全部端口实现状态）、`get_segment_port_for_vm`（按 VM 显示名查找） | 只读 |

每个工具的完整 API 端点与方法见 `skills/vmware-nsx/references/capabilities.md`。

### 工具说明

**Segment**
- `list_segments` — 列出所有 Segment，含类型、子网、网关、传输区域
- `get_segment` — 获取 Segment 详情，含端口和子网配置
- `create_segment` — 创建 Overlay 或 VLAN Segment
- `update_segment` — 更新 Segment 属性（描述、标签、DHCP）
- `delete_segment` — 删除 Segment（检查已连接端口）

**Tier-0 网关**
- `list_tier0_gateways` — 列出所有 Tier-0 网关，含 HA 模式和 transit 子网
- `get_tier0_gateway` — 获取 Tier-0 详情：HA 模式、故障切换、transit 子网
- `get_bgp_neighbors` — 获取 Tier-0 的 BGP 配置与邻居会话状态
- `configure_tier0_bgp` — 在 Tier-0 的 locale-service 上配置 BGP（local AS、ECMP、inter-SR iBGP）

**Tier-1 网关**
- `list_tier1_gateways` — 列出所有 Tier-1 网关，含关联的 Tier-0 与路由通告
- `get_tier1_gateway` — 获取 Tier-1 详情：Tier-0 链路、路由通告
- `create_tier1_gateway` — 创建 Tier-1 网关并关联 Edge 集群和 Tier-0
- `update_tier1_gateway` — 更新 Tier-1 属性（路由通告、Tier-0 链路）
- `delete_tier1_gateway` — 删除 Tier-1 网关；先做只读预检，仍有 segment、NAT 规则、静态路由、服务接口、其他 locale-service、IPsec / L2 VPN 服务、DNS 转发器或负载均衡服务依赖它时拒绝删除、不做任何改动，并列出阻塞对象的 ID

**NAT**（仅 Tier-1）
- `list_nat_rules` — 列出 Tier-1 网关上的 NAT 规则
- `create_nat_rule` — 创建 SNAT/DNAT/反射 NAT 规则（同 `rule_id` 重发即为更新）
- `delete_nat_rule` — 删除 NAT 规则

**静态路由**（Tier-0 / Tier-1）
- `list_static_routes` — 列出网关上的静态路由
- `create_static_route` — 添加静态路由
- `delete_static_route` — 删除静态路由

**IP 池**
- `list_ip_pools` — 列出 IP 地址池及使用统计
- `get_ip_pool_usage` — 查看单个池的已分配 IP
- `create_ip_pool` — 创建 IP 地址池（含一个静态子网与分配范围）
- `delete_ip_pool` — 永久删除 IP 地址池

**Fabric 清单**
- `list_transport_zones` — 列出传输区域（OVERLAY / VLAN）
- `list_transport_nodes` — 列出传输节点及类型、状态
- `list_edge_clusters` — 列出 Edge 集群及成员数、部署类型

**健康与排障**
- `list_nsx_alarms` — 列出指定 severity 的活跃 NSX 告警（精确匹配，非"及以上"；需逐档查询）
- `get_transport_node_status` — 传输节点连接状态、隧道/pNIC 计数
- `get_edge_cluster_status` — Edge 集群成员状态
- `get_nsx_manager_status` — NSX Manager 集群健康状态
- `get_logical_port_status` — 按 Segment 查看全部端口的实现状态（attachment、realized bindings、传输节点）
- `get_segment_port_for_vm` — 按 VM 显示名查找其连接的 Segment（经 /fabric/vifs）

## 常见工作流

### 创建应用网络（Segment + T1 网关 + NAT）

1. 创建网关：`vmware-nsx gateway create-t1 app-t1 --edge-cluster edge-cluster-01 --tier0 tier0-gw`
2. 创建 Segment：`vmware-nsx segment create app-web-seg --name app-web-seg --tz <tz-overlay-path> --subnet 10.10.1.1/24`
3. 添加 SNAT：`vmware-nsx nat create app-t1 --action SNAT --source 10.10.1.0/24 --translated 172.16.0.10`
4. 验证：`vmware-nsx segment list` 和 `vmware-nsx nat list app-t1`

任何写操作前可加 `--dry-run` 预览。

### 检查网络健康

1. Manager 状态：`vmware-nsx health manager-status`
2. 传输节点：`vmware-nsx health transport-nodes`
3. Edge 集群：`vmware-nsx health edge-clusters`
4. 告警：`vmware-nsx health alarms --severity HIGH`（精确匹配单一级别，需逐档查询）

### 排查 VM 连通性

1. 查找 VM 所在 Segment：`vmware-nsx troubleshoot vm-segment <vm-display-name>`
2. 检查端口实现状态：`vmware-nsx troubleshoot port-status <segment-id>`（该 Segment 全部端口的 attachment / realized bindings / 传输节点）
3. 检查路由：`vmware-nsx gateway routes-t1 app-t1`
4. 检查 BGP：`vmware-nsx gateway bgp-neighbors tier0-gw`

## CLI

```bash
# Segment
vmware-nsx segment list
vmware-nsx segment get app-web-seg
vmware-nsx segment create app-web-seg --name app-web-seg --tz <tz-overlay-path> --subnet 10.10.1.1/24
vmware-nsx segment delete app-web-seg

# 网关
vmware-nsx gateway list-t0
vmware-nsx gateway list-t1
vmware-nsx gateway create-t1 app-t1 --edge-cluster edge-cluster-01 --tier0 tier0-gw
vmware-nsx gateway bgp-neighbors tier0-gw
vmware-nsx gateway routes-t1 app-t1

# NAT（写操作有双重确认 + --dry-run 预览）
vmware-nsx nat list app-t1
vmware-nsx nat create app-t1 --action SNAT --source 10.10.1.0/24 --translated 172.16.0.10
vmware-nsx nat delete-rule --tier1 app-t1 --rule-id rule-01

# 静态路由
vmware-nsx route list app-t1
vmware-nsx route create app-t1 --network 192.168.100.0/24 --next-hop 10.10.1.254

# IP 池
vmware-nsx ippool list
vmware-nsx ippool create tep-pool
vmware-nsx ippool add-subnet tep-pool --start 192.168.100.10 --end 192.168.100.50 --cidr 192.168.100.0/24

# 健康与排障
vmware-nsx health alarms --severity HIGH   # 精确匹配：LOW | MEDIUM | HIGH | CRITICAL
vmware-nsx health transport-nodes
vmware-nsx health manager-status
vmware-nsx troubleshoot vm-segment my-vm-01          # VM 显示名
vmware-nsx troubleshoot port-status app-web-seg      # Segment ID

# 环境诊断
vmware-nsx doctor
```

## MCP Server

**v1.5.15+ 推荐方式**：完成 `uv tool install vmware-nsx-mgmt` 后，**一条命令启动 MCP**：

```bash
# 推荐 — 单命令，无网络依赖
vmware-nsx mcp

# 或通过 Docker
docker compose up -d
```

### Agent 配置

将以下内容添加到 AI Agent 的 MCP 配置文件：

```json
{
  "mcpServers": {
    "vmware-nsx": {
      "command": "vmware-nsx",
      "args": ["mcp"],
      "env": {
        "VMWARE_NSX_CONFIG": "~/.vmware-nsx/config.yaml"
      }
    }
  }
}
```

<details>
<summary>备选方案：uvx（不安装）或 legacy 入口</summary>

```bash
# 不想安装，临时运行（每次需要联网 resolve 依赖）
uvx --from vmware-nsx-mgmt vmware-nsx mcp

# 旧 entry point（仍可用，向后兼容）
vmware-nsx-mcp
```

> **公司 TLS 代理网络下？** uvx 可能报 `invalid peer certificate: UnknownIssuer`。
> 推荐使用上面的 `vmware-nsx mcp`（无需联网），或 `export UV_NATIVE_TLS=true`。

</details>

更多 Agent 配置模板（Claude Code、Cursor、Goose、Continue 等）见 [examples/mcp-configs/](examples/mcp-configs/)。

## 版本兼容性

| NSX 版本 | 支持 | 说明 |
|----------|------|------|
| NSX 4.x | 完整 | 最新 Policy API，全部功能 |
| NSX-T 3.2 | 完整 | 所有功能可用 |
| NSX-T 3.1 | 完整 | 路由表格式略有差异 |
| NSX-T 3.0 | 兼容 | IP 池子网 API 在此版本引入 |
| NSX-T 2.5 | 有限 | Policy API 不完整，部分工具可能失败 |
| NSX-V (6.x) | 不支持 | 完全不同的 API（基于 SOAP） |

### VCF 兼容性

| VCF 版本 | 捆绑 NSX | 支持 |
|----------|----------|------|
| VCF 5.x | NSX 4.x | 完整 |
| VCF 4.3-4.5 | NSX-T 3.1-3.2 | 完整 |

## 安全

| 功能 | 说明 |
|------|------|
| 只读为主 | 33 个工具中 20 个只读 |
| 双重确认 | CLI 写操作需两次确认 |
| --dry-run | 所有写操作支持预览模式 |
| 依赖检查 | 删除 segment 时若仍有端口连接则拒绝；删除 Tier-1 时若仍有 segment、NAT 规则、静态路由、接口或 VPN / DNS 转发器 / 负载均衡服务依赖它则拒绝，且不做任何改动（`--dry-run` 执行同样的检查）。其他删除操作不做预检 |
| 输入验证 | CIDR、IP、VLAN ID、网关存在性验证 |
| 审计日志 | 所有操作记录到 `~/.vmware-nsx/audit.log`（JSON Lines） |
| 无防火墙操作 | 无法创建/修改 DFW 规则或安全组 |
| 凭据安全 | 密码只从环境变量读取，不存于配置文件 |
| Prompt 注入防护 | NSX 对象名称经过控制字符清理 |
| TLS 说明 | 默认对自签名证书禁用 TLS 验证；生产环境建议启用 |

## 常见问题排查

| 问题 | 原因与解决 |
|------|-----------|
| "Segment not found" | Policy API 使用 Segment `id` 而非 `display_name`。运行 `segment list` 获取准确 ID。 |
| NAT 创建报 "gateway not found" | NAT 需要 Tier-1（或 Tier-0）网关。用 `gateway list-t1` 确认，网关必须有 Edge 集群。 |
| BGP 邻居停在 Connect/Active | 对端不可达、ASN 不匹配、TCP 179 被阻止、或 MD5 密码不匹配。 |
| 传输节点 "degraded" | TEP 不可达（检查 MTU >= 1600）、NTP 同步问题、或主机交换机配置不匹配。 |
| "Password not found" 错误 | 变量名规则：`VMWARE_NSX_<目标名大写>_PASSWORD`（连字符→下划线）。检查 `~/.vmware-nsx/.env`。 |
| 连接 NSX Manager 超时 | 使用 `vmware-nsx doctor --skip-auth` 跳过高延迟网络的认证检查。 |

## 许可证

[MIT](LICENSE)
