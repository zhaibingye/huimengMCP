# 霜華绘梦 MCP 简明教程

开始前准备 Git、Python 3.11+、uv 和霜華 API Key。 [uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/)

## 部署

打开终端，下载项目并安装依赖。

```powershell
git clone https://github.com/zhaibingye/huimengMCP.git
cd huimengMCP
uv sync --locked
```

在项目目录选择下面一种启动方式。

### 前台启动

```powershell
uv run --locked python server.py
```

使用服务时保持终端打开。

### PM2 进程守护

PM2 让服务在后台运行，并在进程异常退出后自动重启。准备 Node.js 和 npm。如果服务正在前台运行，先按 `Ctrl+C` 停止。

```powershell
npm install -g pm2
pm2 start uv --name huimeng-mcp --interpreter none -- run --locked python server.py
pm2 status
```

已安装 PM2 时可跳过安装命令。状态显示 `online` 后即可连接，日志可用 `pm2 logs huimeng-mcp` 查看。

在 Linux 上需要开机自启时，以运行服务的账户执行 `pm2 startup`，按提示执行生成的命令，再运行 `pm2 save`。Windows 的开机启动方式也可查阅官方说明。 [PM2 开机启动说明](https://pm2.keymetrics.io/docs/usage/startup/)

### 连接客户端

在支持 Streamable HTTP 的 MCP 客户端中添加服务器，并替换示例里的 API Key。

```json
{
  "mcpServers": {
    "huimeng": {
      "url": "http://127.0.0.1:3005/mcp",
      "headers": {
        "Authorization": "Bearer <霜華 API Key>"
      }
    }
  }
}
```

在客户端调用 `list_media_models`，确认连接成功。

如果部署在远程服务器，用 HTTPS 反向代理转发 `/mcp` 和 `/media/`，并保留外部域名和协议。客户端将 `url` 换成对应的 HTTPS 地址，例如 `https://mcp.example.com/mcp`。

## 卸载

1. 前台运行时按 `Ctrl+C`。用 PM2 守护时执行 `pm2 delete huimeng-mcp`。如果之前保存过 PM2 进程列表，删除后执行 `pm2 save --force`，避免开机时重新启动已卸载的服务。
2. 从 MCP 客户端删除 `huimeng` 配置。
3. 如需保留自定义设置，先备份 `config.toml`，再删除克隆的 `huimengMCP` 文件夹。

## 更新

1. 前台运行时按 `Ctrl+C` 停止。用 PM2 守护时执行 `pm2 stop huimeng-mcp`。如果改过 `config.toml`，先备份该文件。
2. 在 `huimengMCP` 目录拉取更新。

   ```powershell
   git pull --ff-only
   ```

3. 拉取成功后，执行 `uv sync --locked` 同步依赖。
4. 同步成功后，按原方式启动。前台运行用 `uv run --locked python server.py`，PM2 守护用 `pm2 restart huimeng-mcp`。之前保存过 PM2 进程列表时，重启后再执行 `pm2 save`。
