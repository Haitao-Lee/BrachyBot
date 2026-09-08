# BrachyBot 出站隧道部署（待接入公网）

状态：部署代码与模板。没有域名、VPS 和验证后的主机密钥时不能上线。
GPU 上现有 LAN 服务 8080 保留；新生产入口是 127.0.0.1:18082。

```
浏览器 HTTPS:443 -> VPS Nginx -> VPS 127.0.0.1:18082
                                ^ SSH -R（GPU 主动连接）
                                -> GPU 127.0.0.1:18082 -> Waitress/BrachyBot
```

## 1. 准备 GPU 节点

以下路径根据已检查的 lht 环境提供；换机器时修改 service 中的两个绝对路径。
所有命令从 `/home/lht/snap/brachyplan/BrachyBot` 执行。

```bash
/home/lht/.conda/envs/brachytherapy/bin/python -m pip install -r deploy/public/requirements.txt
install -d -m 700 ~/.config/brachybot ~/.config/systemd/user
install -m 600 deploy/public/production.env.example ~/.config/brachybot/public.env
install -m 600 deploy/public/ssh_config.example ~/.config/brachybot/ssh_config
install -m 644 deploy/public/brachybot-public.service ~/.config/systemd/user/
install -m 644 deploy/public/brachybot-tunnel.service ~/.config/systemd/user/
```

`install` 会覆盖目标文件：仅用于首次安装；已有配置时先复制备份并合并。
编辑 public.env：填入真实 HTTPS 域名、两个独立随机密钥及有效 LLM 配置。
本文件遵循 systemd EnvironmentFile 格式，不使用 export、$HOME 或变量展开。
使用密码管理器生成并保存密钥；不把密钥放入 URL、Git 或命令行参数。

新环境默认使用独立 `.runtime-public`，避免两个服务同时写现有病例库。
任何生产和 LAN 进程均不得同时使用同一个 runtime；公用迁移必须先停原服务。
初始开通普通用户：

```bash
/home/lht/.conda/envs/brachytherapy/bin/python deploy/public/create_account.py \
  --runtime /home/lht/snap/brachyplan/BrachyBot/.runtime-public --username doctor
```

账号工具需要交互终端并隐藏密码输入；它拒绝在 public 服务运行时操作。
这是运维人员离线开通普通账号，不是新建应用管理员权限。
后续增加账号：停止 public 服务、运行账号工具、重新启动；先等待病例任务结束。

## 2. 准备 VPS 和域名

在选定 VPS 上安装 Nginx、OpenSSH 和 Certbot。DNS A/AAAA 必须指向可达 VPS；
没有配置 IPv6 时不要添加 AAAA。TLS/SSH 入口的网络规则依照 VPS 实际配置设置。
不要改 GPU 路由器端口映射，也不要对公网开放 18082。

创建专用 `brachybot-tunnel` SSH 用户；生成专用 ed25519 密钥放到 GPU：
`~/.config/brachybot/tunnel_ed25519`，私钥 mode 0600。
公钥放入 VPS 此用户的 authorized_keys，禁止复用管理员私钥。
安装 sshd-edge.conf.example 为 SSH drop-in，执行 `sshd -t` 后才 reload。
MaxSessions=0 禁止该账户开启 shell/SFTP，但允许 remote forwarding。
保留当前管理 SSH 会话，核实普通管理员仍能登录。

通过 VPS 控制台或另一条已信任通道核对 SSH host key 指纹，再加入 GPU 专用
known_hosts 文件；不能只依靠未经核实的 ssh-keyscan。配置始终启用 StrictHostKeyChecking。
编辑 ssh_config 的 HostName，然后用 `ssh -F ~/.config/brachybot/ssh_config -G brachybot-edge`
检查最终参数。SSH 不需要读取患者文件，隧道只转发 TCP。

## 3. HTTPS 和反向代理

先按 Certbot 的 DNS 验证或 HTTP 验证流程为实际域名签发证书；尚无证书时不要启用
带 ssl_certificate 的正式配置。首次可临时用只服务 ACME 验证目录的 80 端口站点，
不代理 BrachyBot。验证自动续期及成功续期后的 Nginx reload。

把 nginx.conf.example 中域名和证书路径替换后安装到 VPS 的 http 配置目录。
创建 `/etc/nginx/brachybot-api-key.conf`（root:root 0600），内容为：

```nginx
proxy_set_header X-API-Key "与 GPU public.env 相同的部署密钥";
```

随机密钥使用 URL-safe 字符，避免引号/分号。Nginx root master 读取此文件；
不要在聊天、CI 输出或共享日志中运行 `nginx -T`（它会展开密钥 include）。
使用 `nginx -t` 检验。共享 VPS 上先检查现有 default_server，并配置未知域名拒绝站点。
模板覆盖客户端提交的 X-API-Key 和转发头；浏览器只需要账号、密码和 CSRF Cookie。
公开注册在 Nginx 和 auth_register 两层关闭。

Nginx 的 response/request buffering 均关闭，SSE 立即输出，后端空闲超时为一小时。
500 MiB 上传上限与现有 Flask 限制一致；Waitress 仍会将大请求缓冲到临时文件，
所以应保证 GPU 临时盘空间充足。未实现分片上传或断点续传。
API 禁止共享缓存；访问日志不记录查询参数，错误日志仍可能含 URI，需限制权限与保留期。

## 4. 启动与驻留

```bash
systemctl --user daemon-reload
systemctl --user start brachybot-public.service
systemctl --user start brachybot-tunnel.service
systemctl --user status brachybot-public.service brachybot-tunnel.service
```

ExecStartPre 自动预检环境；未填密钥/域名、不安全开发开关会拒绝启动。
确认服务工作后才 `systemctl --user enable brachybot-public.service brachybot-tunnel.service`。
已检查的机器 `Linger=no`：开机无人登录自动运行需要管理员执行
`loginctl enable-linger lht`；仅 enable 用户 unit 不足以保证开机驻留。

当前病例任务包含进程内状态，保持单 Waitress 进程、多线程。
16 线程仅是受邀小规模试用起点，SSE 会占线程；没有承诺多用户 GPU 并行能力。
不要启动多个进程共享 runtime，也不要将此配置直接扩成多副本。
systemd 会清理子进程，故服务停止会中断任务；需要等待任务结束再升级。

## 5. 验收与切换

```bash
python deploy/public/check_public.py https://实际域名
```

自动检查：TLS 校验、入口可达、匿名 API 被拒绝、HSTS 和禁止缓存。
它不能替代真实浏览器验收：用合成/脱敏测试 case 测试登录、CSRF、两个账号隔离、
大 CT 上传、SSE 首个事件立即出现、数分钟任务、断网重连、病例切换、viewer 和 PDF。
检查浏览器不再携带部署密钥；检查 18082 无公网可达性。
现有登录 UI 可能仍显示可选访问密钥/注册选项；入口自动注入密钥，注册只返回联系管理员，
没有把 UI 文案清理当作新权限系统。

迁移旧病例前：停止原服务并确认没有子任务，备份整个 runtime（数据库及数组 sidecar 一起），
验证恢复，再配置新服务指向该目录。不要只复制 sqlite，不要在线 rsync 后假设快照一致。
首次 public 服务需预留模型/GPU并发容量；不要与 LAN 同时运行重型任务做压力试验。

## 6. 回滚与实际边界

尚未迁移病例时，停止 tunnel/public 两个 unit 即可撤销公网接入，原 8080 服务继续使用。
已经切换相同病例目录时：先停新服务，确认所有子进程停止，再以原命令启动旧服务。
保留原配置和数据备份，不覆盖正在写入的 runtime。不自动修改 DNS 或执行递归删除。

本交付没有购买域名/VPS、签发证书、连接真实隧道、迁移患者数据或启用线上服务。
已有应用账号、CSRF、病例隔离和配额继续复用；没有新增 SSO、邀请邮件、WAF、GPU 队列、
自动备份平台或完整监控。接入公网前还需确定允许用户、数据存放区域和备份安排。

参考：
- https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- https://man.openbsd.org/ssh
- https://man.openbsd.org/sshd_config
- https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html
- https://flask.palletsprojects.com/en/stable/deploying/
