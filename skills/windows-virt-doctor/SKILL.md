---
name: windows-virt-doctor
description: Windows 虚拟化诊断工具。诊断 WSL2/Hyper-V/Docker 创建失败问题：HNS 损坏、ICS 冲突、0x80072726/0x80072f78/RPC 错误、Hyper-V 服务异常。触发词：WSL2、Hyper-V、虚拟化、HNS、虚拟机创建失败、0x80072726、0x80072f78、Docker 启动失败
---

# Windows 虚拟化诊断 · 框架化排查

## 适用场景

当出现以下任一情况时使用：
- `wsl --set-version` 报 `0x80072726` (WSAEADDRINUSE)
- `wsl --install` 报 `0x80072f78` (下载失败)
- `wsl --install` 报 `RPC_S_CALL_FAILED`
- `wsl --install` 报 `WSL_E_DISTRO_NOT_FOUND`
- Docker Desktop 无法启动（WSL2 后端）
- Hyper-V 虚拟机创建失败
- `Get-HNSNetwork` 返回空

## 第0级：前置检查（先执行，再分级）

### 0A：代理检查（2026-05-10 新增实战经验）

**这是最容易忽略但最常见的根因。** 装了 Vortex/Clash/V2Ray/Sing-Box 等代理软件的机器，WSL2 安装失败的 90% 是代理干扰。

```powershell
# 检查是否有代理/VPN 进程在运行
tasklist | findstr /i "vortex clash v2ray sing-box xray trojan proxifier tun wintun"

# 如果查出任何进程 → 先退出代理再继续
# 托盘图标右键 → 退出（Exit/Quit）
```

**为什么代理会导致 WSL2 失败（双重打击）：**

| 阶段 | 问题 | 表现 |
|------|------|------|
| 下载发行版 | TUN 模式拦截 DNS → GitHub 域名解析失败 | `WININET_E_NAME_NOT_RESOLVED` |
| 创建虚拟网络 | TUN 虚拟网卡占用地址段 → HNS 创建 Default Switch 冲突 | `0x80072726` (WSAEADDRINUSE) |

**规则：装了代理软件的机器，装 WSL 发行版时务必先退代理。** 退后再执行 `netsh winsock reset`，然后正常安装。安装完再开代理。

### 0B：基础检查

```powershell
# 查看 HNS 网络（核心诊断命令）
Get-HNSNetwork

# 检查 vEthernet Default Switch
Get-NetAdapter | Where-Object {$_.Name -like "*vEthernet*"}

# 检查 NAT 状态
Get-NetNat

# 检查 WSL 版本和状态
wsl -l -v

# 检查 WSL 内核
wsl --version

# 检查 Hyper-V 服务
Get-Service vmcompute, hns, vmms
```

### 诊断结果分级

| 状态 | 含义 | 下一步 |
|------|------|--------|
| HNS 有网络 + NetNat 存在 | HNS 正常 | 跳转到第1级 |
| HNS 有网络 + NetNat 为空 | HNS 部分正常 | 跳转到第2级 |
| HNS 为空 | HNS 损坏 | 跳转到第2级 |
| vEthernet 不存在 | Default Switch 丢失 | 跳转到第2级 |
| vmcompute/hns 服务未运行 | 服务异常 | 跳转到第0.5级 |

### 第0.5级：服务级修复

```powershell
# 重启 Hyper-V 相关服务
Restart-Service vmcompute -Force
Restart-Service hns -Force
Start-Sleep -Seconds 10

# 检查服务状态
Get-Service vmcompute, hns, vmms
```

如果服务无法启动 → 跳转到第2级。

---

### 第1级：标准修复

#### 1A：简单转换（HNS 正常时）

```powershell
# 关闭 WSL
wsl --shutdown

# 等待几秒
Start-Sleep -Seconds 5

# 直接转换
wsl --set-version <DistroName> 2
```

- 成功 → 已完成 ✅
- 报 `0x80072726` → 走 1B
- 报 `RPC_S_CALL_FAILED` → 重启 vmcompute 服务再试

#### 1B：重建 WSL 网络基础设施

```powershell
# 关闭 WSL
wsl --shutdown

# 重建 WSL 网络
wsl --install --no-distribution

# 等待 HNS 创建 WSL 网络
Start-Sleep -Seconds 10
Get-HNSNetwork

# 再转换
wsl --set-version <DistroName> 2
```

- 成功 → 已完成 ✅
- 仍失败 → 走 1C

#### 1C：导出 + 重新导入（绕过转换流程）

```powershell
# 备份当前发行版
wsl --export <DistroName> <BackupPath>\backup.tar

# 验证导出文件
ls -lh <BackupPath>\backup.tar

# 注销旧发行版
wsl --unregister <DistroName>

# 以 WSL2 模式重新导入
wsl --import <DistroName> <InstallPath> <BackupPath>\backup.tar --version 2
```

- 成功 → 已完成 ✅
- 仍报 `0x80072726` → 走第2级

---

### 第2级：深度修复（HNS 损坏 / ICS 冲突）

#### 2A：重置 HNS 数据库

```powershell
# Step A1: 关闭所有 WSL
wsl --shutdown

# Step A2: 停止 Hyper-V 服务
Stop-Service vmcompute -Force
Stop-Service hns -Force

# Step A3: 删除 HNS 注册表状态（强制重建）
Remove-Item -Path "HKLM:\SYSTEM\CurrentControlSet\Services\hns\State" -Recurse -Force -ErrorAction SilentlyContinue

# Step A4: 重启服务
Start-Service hns
Start-Service vmcompute

# Step A5: 等待重建
Start-Sleep -Seconds 15

# Step A6: 验证
Get-HNSNetwork
```

- HNS 重建成功（有网络） → 回到第1级
- HNS 仍为空 → 走 2B

#### 2B：强制删除 Default Switch

```powershell
# Step B1: 删除 Default Switch（解除 ICS 绑定）
Remove-VMSwitch "Default Switch" -Force
# 如果失败（ICS占用），走 2C

# Step B2: 重启电脑
Restart-Computer
```

重启后检查 `Get-HNSNetwork` → 应该已经自动重建。
如果仍有问题 → 走 2C。

#### 2C：手动创建 WSL NAT 网络

```powershell
# 创建 WSL 专用的 NAT 网络
$networkJson = @{
    Name = "WSL"
    Type = "NAT"
    Subnets = @(
        @{
            AddressPrefix = "172.20.0.0/20"
            GatewayAddress = "172.20.0.1"
        }
    )
} | ConvertTo-Json -Depth 10

New-HNSPolicy -Type "Network" -Data $networkJson

# 验证
Get-HNSNetwork

# 回到第1级重试转换
wsl --set-version <DistroName> 2
```

---

### 第3级：系统级修复（降级方案）

如果以上所有方案都失败：

#### 方案 A：检查是否为 Windows Insider Build 的已知 bug

```powershell
# 查看当前 Windows 版本和 Build
winver
# 或
[System.Environment]::OSVersion.Version
# 或查看 Insider 通道设置
# 设置 → Windows 更新 → Windows 预览体验计划
```

如果确认是 Insider Build：

1. **等待下一个大版本更新**（如 26H1/26H2）修复
2. **可选**：退出 Insider 通道，回退到稳定版

#### 方案 B：使用 WSL1 作为替代（功能完备方案）

WSL1 在以下场景与 WSL2 无明显性能差异：
- Python 开发（Hermes Agent ✅）
- Node.js 开发
- Shell 脚本
- Git 操作
- 文件系统 I/O（WSL1 甚至更快）

需要 WSL2 的场景（WSL1 不适用）：
- Docker Desktop WSL2 后端
- 需要完整 Linux 内核的软件（如 systemd 原生支持）
- 需要 eBPF/内核模块 的场景

```powershell
# 确认当前为 WSL1
wsl -l -v

# 设置默认版本为 WSL1（避免误操作）
wsl --set-default-version 1
```

#### 方案 C：切换到 VirtualBox（完全替代 Hyper-V）

- 安装 Oracle VirtualBox 7.x
- 在 VirtualBox 中创建 Ubuntu 22.04 VM
- 安装 Hermes Agent
- VirtualBox 不依赖 Hyper-V，完全独立运行

---

## 错误码速查表

| 错误码 | 含义 | 常见根因 | 推荐方案 |
|--------|------|---------|---------|
| `0x80072726` (WSAEADDRINUSE) | 地址已被占用 | **代理 TUN 拦截（最常见）** > HNS 损坏 > Default Switch 冲突 | **先退代理 → netsh winsock reset → 重试**，若失败再走第2级 |
| `RPC_S_CALL_FAILED` | RPC 通信中断 | vmcompute 服务未就绪 | 重启 vmcompute 服务 |
| `0x80072f78` | 下载失败 | 代理/SSL/网络问题 | 退出代理后重试，或用镜像安装 |
| `WSL_E_DISTRO_NOT_FOUND` | 发行版未注册 | 创建失败后回滚 | wsl --import 手动注册 |
| `CreateVm` 通用失败 | VM 创建失败 | HNS/ICS/Hyper-V 底层问题 | 从第0级开始诊断 |

---

## 代理兼容性诊断

如果 `wsl --install -d <Distro>` 下载失败（0x80072f78）：

```powershell
# 检查代理配置
$env:HTTP_PROXY
$env:HTTPS_PROXY

# 确认 winget 可用
/c/Users/$env:USERNAME/AppData/Local/Microsoft/WindowsApps/winget.exe search Ubuntu

# 用 winget 替代 wsl 下载
/c/Users/$env:USERNAME/AppData/Local/Microsoft/WindowsApps/winget.exe install Canonical.Ubuntu.2204

# 然后手动导入
wsl --import <DistroName> <InstallPath> <install.tar.gz> --version 1
```

---

## 日志记录

执行诊断时，自动在 `~/.clawdbot/diagnostics/` 下记录每次诊断结果：

```powershell
# 诊断快照保存
$diagDir = "$env:USERPROFILE\.clawdbot\diagnostics"
New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = @{
    Timestamp = $timestamp
    HNSNetworks = Get-HNSNetwork | ConvertTo-Json
    HNSState = Get-HNSEndpoint | ConvertTo-Json
    NetNat = Get-NetNat | ConvertTo-Json
    VMSwitches = Get-VMSwitch | Select-Object Name, SwitchType, Notes | ConvertTo-Json
    WSLVersion = wsl --version 2>&1 | Out-String
    WSLDistros = wsl -l -v 2>&1 | Out-String
    HVServices = Get-Service vmcompute, hns, vmms | Select-Object Name, Status, StartType | ConvertTo-Json
}
$report | ConvertTo-Json | Out-File "$diagDir\virt-snapshot-$timestamp.json"
```

---

## 经验教训（来自实战）

1. **代理软件是第一检查项**：装了 Vortex/Clash/V2Ray/Sing-Box 的机器，90% 的 WSL2 安装失败是代理干扰导致的。**不要先查 HNS，先退代理再试。** TUN 模式会同时影响 DNS 解析（下载失败）和 HNS 网络创建（地址冲突）。

2. **`netsh winsock reset` 比重建 HNS 注册表更快**：当退出代理后 `0x80072726` 仍在，先跑这个命令再重试，比深度修复 HNS 注册表省 15 分钟。

3. **WSL2 安装失败是两阶段问题**：不能只看一个错误码就断定根因。第一阶段（下载发行版）是网络问题，第二阶段（创建虚拟交换机）是 HNS 问题，两个阶段可能同时被代理影响。

4. **HNS 损坏优先于所有排查**：`Get-HNSNetwork` 为空时，不要浪费时间去排查网卡冲突/端口占用，直接走深度修复

5. **ICS (Internet Connection Sharing) 是删除 Default Switch 的常见阻碍**：需要先停掉或绕过

6. **`wsl --install --no-distribution` 不能修复损坏的 HNS**：它只在 HNS 正常时创建 WSL 专用的 NAT 网络

7. **导出+重新导入 (`wsl --export + --import --version 2`) 绕过转换流程**：当 `wsl --set-version` 卡住时的备选路径

8. **Insider Build 的 HNS bug 可能无解**：如果深度修复都失败，很可能不是配置问题，而是 Windows 版本 bug，等更新

9. **WSL1 不是降级，是合理的替代方案**：对绝大多数开发场景完全够用

10. **先执行再询问比逐步排查更高效**：给出完整的 3 步修复脚本让用户一次跑完，比每步等反馈再走下一步快得多。`退代理 → netsh winsock reset → ubuntu2204.exe` 三步 10 分钟能搞定的事，分步排查可能要 30 分钟。
