# 验证记录 — 2026-09-08

部署基础代码已同步到 `rtx3090_external:<workspace>/BrachyBot`。
未启用生产 unit、未重启现有 8080 服务、未迁移病例。

已通过：
- `tests/test_public_deployment.py tests/test_workspace_auth.py`：32 passed，3 个第三方 SWIG 弃用警告。
- `tests/test_public_http.py`：1 passed。真实 Waitress + 完整 create_app，临时独立 runtime。
- `tests/test_public_proxy.py`：1 passed。真实 Nginx + 临时自签名证书 + loopback SSE 测试后端。
- systemd-analyze --user verify：public 和 tunnel 两个 unit 通过。
- ssh -G：专用配置成功解析；不连接远端。

代理测试证实：响应结束前可读到第一条 SSE；部署密钥在代理端注入；
客户端伪造的 X-Forwarded-For/Proto 被覆盖；API no-store 和 HSTS 生效。
真实应用测试证实：未知 Host 和 HTTP 请求拒绝，匿名 API 返回 401，注册返回 403。
账号测试证实：受邀账号可登录、安全 Cookie、CSRF、原有账号/病例隔离回归通过。

测试依赖只下载/解包到 `/tmp`：Waitress 3.0.2，Ubuntu Nginx 1.18 用于配置兼容验证；
没有安装为系统服务。正式 VPS 应安装受支持且已打安全补丁的 Nginx 软件包。
发行版缓存的较新 Nginx 包链接返回 404，测试改用已有可下载版本；
这不构成对该旧版本用于公网生产的推荐。

仍待真实基础设施验证：域名 DNS、公开可信证书及续期、SSH 主机身份与隧道重连、
公网端口隔离、500 MiB 实际文件上传、长时间规划、浏览器端到端、多用户 GPU 负载、
备份恢复。没有将这些尚未执行的检查报告为完成。
