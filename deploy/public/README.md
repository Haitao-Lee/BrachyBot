# BrachyBot Outbound Tunnel Deployment (Pending Public Network Access)

Status: deployment code and templates. Cannot go live without a domain, VPS, and verified host keys.
The existing LAN service 8080 on the GPU is retained; the new production entry point is 127.0.0.1:18082.

```
Browser HTTPS:443 -> VPS Nginx -> VPS 127.0.0.1:18082
                                ^ SSH -R (GPU initiates connection)
                                -> GPU 127.0.0.1:18082 -> Waitress/BrachyBot
```

## 1. Prepare the GPU Node

The following paths are based on the inspected brachybot environment; when switching machines, modify the two absolute paths in the service.
Run all commands from `<workspace>/BrachyBot`.

```bash
<conda-env>/bin/python -m pip install -r deploy/public/requirements.txt
install -d -m 700 ~/.config/brachybot ~/.config/systemd/user
install -m 600 deploy/public/production.env.example ~/.config/brachybot/public.env
install -m 600 deploy/public/ssh_config.example ~/.config/brachybot/ssh_config
install -m 644 deploy/public/brachybot-public.service ~/.config/systemd/user/
install -m 644 deploy/public/brachybot-tunnel.service ~/.config/systemd/user/
```

`install` overwrites target files: use only for first-time installation; if configuration already exists, copy a backup first and merge.
Edit public.env: fill in the real HTTPS domain, two independent random keys, and a valid LLM configuration.
This file follows the systemd EnvironmentFile format and does not use export, $HOME, or variable expansion.
Use a password manager to generate and store keys; do not put keys in URLs, Git, or command-line arguments.

New environments use an independent `.runtime-public` by default, to avoid both services writing to the existing case library simultaneously.
No production or LAN process may use the same runtime at the same time; for a shared migration, you must first stop the original service.
Initial provisioning of a regular user:

```bash
<conda-env>/bin/python deploy/public/create_account.py \
  --runtime <workspace>/BrachyBot/.runtime-public --username doctor
```

The account tool requires an interactive terminal and hides password input; it refuses to operate while the public service is running.
This is offline provisioning of a regular account by an operator, not the creation of application administrator privileges.
To add accounts later: stop the public service, run the account tool, then restart; first wait for case tasks to finish.

## 2. Prepare the VPS and Domain

Install Nginx, OpenSSH, and Certbot on the selected VPS. DNS A/AAAA must point to a reachable VPS;
do not add AAAA when IPv6 is not configured. Set the network rules for the TLS/SSH entry point according to the VPS's actual configuration.
Do not change the GPU router's port mapping, and do not expose 18082 to the public network.

Create a dedicated `brachybot-tunnel` SSH user; generate a dedicated ed25519 key and place it on the GPU:
`~/.config/brachybot/tunnel_ed25519`, private key mode 0600.
Place the public key in this user's authorized_keys on the VPS; do not reuse an administrator private key.
Install sshd-edge.conf.example as an SSH drop-in, and run `sshd -t` before reloading.
MaxSessions=0 prevents this account from opening a shell/SFTP but allows remote forwarding.
Keep the current management SSH session and verify that a regular administrator can still log in.

Verify the SSH host key fingerprint through the VPS console or another already-trusted channel, then add it to the GPU's dedicated
known_hosts file; do not rely solely on an unverified ssh-keyscan. The configuration always enables StrictHostKeyChecking.
Edit the HostName in ssh_config, then use `ssh -F ~/.config/brachybot/ssh_config -G brachybot-edge`
to check the final parameters. SSH does not need to read patient files; the tunnel only forwards TCP.

## 3. HTTPS and Reverse Proxy

First issue a certificate for the real domain via Certbot's DNS validation or HTTP validation flow; do not enable the
formal configuration with ssl_certificate before a certificate exists. For the first time, you may temporarily use an 80-port site
that serves only the ACME validation directory, without proxying BrachyBot. Verify automatic renewal and the Nginx reload after successful renewal.

Replace the domain and certificate paths in nginx.conf.example, then install it to the VPS's http configuration directory.
Create `/etc/nginx/brachybot-api-key.conf` (root:root 0600) with the following content:

```nginx
proxy_set_header X-API-Key "与 GPU public.env 相同的部署密钥";
```

Use URL-safe characters for the random key, avoiding quotes/semicolons. The Nginx root master reads this file;
do not run `nginx -T` in chat, CI output, or shared logs (it expands the key include).
Validate with `nginx -t`. On a shared VPS, first check the existing default_server and configure a rejection site for unknown domains.
The template overrides the client-submitted X-API-Key and forwarding headers; browsers only need an account, password, and CSRF cookie.
Public registration is disabled at both the Nginx and auth_register layers.

Nginx response/request buffering is both disabled, SSE outputs immediately, and the backend idle timeout is one hour.
The 500 MiB upload limit matches the existing Flask limit; Waitress still buffers large requests to a temporary file,
so ensure sufficient free space on the GPU temporary disk. Chunked upload or resumable transfer is not implemented.
The API disallows shared caching; access logs do not record query parameters, and error logs may still contain the URI, so restrict permissions and retention.

## 4. Startup and Persistence

```bash
systemctl --user daemon-reload
systemctl --user start brachybot-public.service
systemctl --user start brachybot-tunnel.service
systemctl --user status brachybot-public.service brachybot-tunnel.service
```

ExecStartPre automatically pre-checks the environment; startup is refused if keys/domain are missing or an insecure development switch is set.
Only after confirming the service works, run `systemctl --user enable brachybot-public.service brachybot-tunnel.service`.
The inspected machine has `Linger=no`: to run automatically at boot with no one logged in, an administrator must run
`loginctl enable-linger brachybot`; merely enabling the user unit is not enough to guarantee boot persistence.

The current case tasks include in-process state, so keep a single Waitress process with multiple threads.
16 threads is only a starting point for an invited small-scale trial; SSE occupies threads; there is no promise of multi-user GPU parallelism.
Do not start multiple processes sharing a runtime, and do not directly scale this configuration into multiple replicas.
systemd cleans up child processes, so stopping the service interrupts tasks; you need to wait for tasks to finish before upgrading.

## 5. Acceptance and Cutover

```bash
python deploy/public/check_public.py https://实际域名
```

Automated checks: TLS verification, entry point reachability, anonymous API rejection, HSTS, and no-cache.
It cannot replace real browser acceptance: use synthetic/desensitized test cases to test login, CSRF, isolation of the two accounts,
large CT upload, SSE first event appearing immediately, multi-minute tasks, network-reconnect, case switching, viewer, and PDF.
Check that the browser no longer carries the deployment key; check that 18082 has no public reachability.
The existing login UI may still show optional access key/registration options; the entry point automatically injects the key, and registration only returns "contact administrator";
clearing the UI copy was not treated as a new permission system.

Before migrating old cases: stop the original service and confirm there are no child tasks, back up the entire runtime (database and array sidecar together),
verify the restore, then configure the new service to point to that directory. Do not copy only the sqlite, and do not assume snapshot consistency after an online rsync.
The first public service needs reserved model/GPU concurrency capacity; do not run heavy tasks simultaneously with the LAN for stress tests.

## 6. Rollback and Practical Boundaries

When cases have not yet been migrated, stopping both the tunnel/public units revokes public access, and the original 8080 service continues to be used.
If the same case directory has already been switched: first stop the new service, confirm all child processes have stopped, then start the old service with the original command.
Keep the original configuration and data backups, and do not overwrite a runtime that is being written to. Do not automatically modify DNS or perform recursive deletion.

This delivery does not purchase a domain/VPS, issue certificates, connect a real tunnel, migrate patient data, or enable the online service.
Existing application accounts, CSRF, case isolation, and quotas continue to be reused; no SSO, invitation emails, WAF, GPU queue,
automatic backup platform, or complete monitoring has been added. Before connecting to the public network, you still need to determine allowed users, data storage region, and backup arrangements.

References:
- https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- https://man.openbsd.org/ssh
- https://man.openbsd.org/sshd_config
- https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html
- https://flask.palletsprojects.com/en/stable/deploying/
