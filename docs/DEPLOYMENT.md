# KnowMotion 公网容器部署

生产入口使用 `docker-compose.production.yml`，与原来的 Temporal 本地联调配置分开。
`app` 是包含前端、API、Agent、Manim、Remotion、FFmpeg、LaTeX 和字体的应用镜像；
`web` 使用 Nginx 官方镜像，在同一个域名下转发网页、API、视频和进度请求。

## 当前域名、HTTPS 与并发配置

网站：<https://knowmotion.gragonapi.com/>；工作台：<https://knowmotion.gragonapi.com/workspace>。
该域名的 HTTP 请求自动跳转 HTTPS，直接 IP 的 HTTP 入口仍保留。
Cloudflare 橙云代理已可访问源站 HTTPS；Cloudflare 控制台的 SSL/TLS 模式应使用 **Full (strict)**，
本次没有通过 API 修改 Cloudflare 账户设置。

当前应用镜像为 `knowmotion:production`，固定标签 `knowmotion:2026-11-15-showcase`，
ID 为 `sha256:31fa97f3826336e1c9d66db074718b4a753987d75af88afbedd2f77a5a85cc64`。
`RENDER_CONCURRENCY=4` 控制同一视频内的分镜并行；通用和历史流程均遵守此配置。
全站仍使用 `LOCAL_WORKERS=1`，最多一个活动视频任务。
服务器的 Remotion 单分镜内部并发保留 `REMOTION_CONCURRENCY=1`，避免与四分镜并行相乘；
历史配音并发仍最多为 2。本地配置、设置默认值和 `.env.example` 的分镜并发也已改为 4。

Let's Encrypt 源站证书位于 `/etc/letsencrypt/live/knowmotion.gragonapi.com/`，
Nginx 以只读方式挂载整个 `/etc/letsencrypt`，监听 443。`certbot.timer` 定期检查续期，
成功续期后 `/etc/letsencrypt/renewal-hooks/deploy/knowmotion.sh` 检查并重载 Nginx。
ACME 的 HTTP 验证目录为 `/var/lib/letsencrypt/.well-known/acme-challenge/`。
证书私钥和 ACME 账户数据不进入应用镜像或代码仓库。

浏览器 HTTPS 访问、HTTP 自动跳转、视频 Range 下载、源站证书验证均通过，
Certbot 续期演练成功，并实际执行了 Nginx 检查与重载钩子。
上一版并发调度、渲染取消、成片顺序和公共单任务回归共 36 项通过；未额外生成新视频。
以下保留首次部署时的真实成片验收记录，它不是并发 4 的新成片验收。

## 2026-11-15 首页示例视频更新

首页四个主题使用用户提供的原始 MP4，保留现有封面，移除待上传说明。
源文件位于 `frontend/src/assets/showcase/`，通过 Vite 的 `?url` 导入；
构建时生成带内容哈希的文件名，随应用镜像发布，播放示例不会创建后台任务。

| 首页主题 | 用户提供的文件 | 发布资源 |
|---|---|---|
| 导数 | 导数demo.mp4 | `/assets/derivative-B5HIQQxK.mp4` |
| 勾股定理 | 勾股demo.mp4 | `/assets/geometry-D1nZiXaw.mp4` |
| 概率 | 概率demo.mp4 | `/assets/probability-wq-6wV_S.mp4` |
| 张骞 | 张骞demo.mp4 | `/assets/history-DeFzx1x9.mp4` |

四片均为 720p、30fps、H.264/AAC，支持渐进播放。镜像内文件 SHA-256 与用户原文件一致，
没有转码、改速或重新生成。前端在服务器构建，等待现有生成任务结束后切换容器，
旧版本保留为 `knowmotion:before-showcase-release`。
线上四片首尾 Range 请求均返回 206，响应字节与原文件一致；浏览器实际播放及跳转至
65% 位置均通过，播放器无媒体错误，控制台无错误或警告。首页加载新版脚本
`index-HcaoanFE.js`，健康检查正常。
本次仅替换展示资源，生成管线及其既有成片验收记录保持独立。

## 2026-11-15 停止制作与泰勒任务修复

失败任务 `e8d57852-b9f1-45ee-822f-cca7f5fac812` 的主题为“生成一个讲泰勒公式的视频”。
错误出在 MiniMax 真实词时间解析：`sin x` 等文本的空格也有合法字符范围和实测起止时间，
旧解析器使用 `provider_text.strip()` 检查非空，误把这些空格词条当作无效数据。
场景 01 和 04 因此报 `MiniMax word offsets or timestamps are invalid or non-monotonic`；
原始时间并没有倒退，这次失败也不是分镜并发为 4 导致。
重复恢复读取同一份配对音频与原始时间缓存，所以会再次触发同一错误。

新解析器保留具有有效原文范围、有效实测时间的空格；真正的空字符串、越界、零时长、
非有限数值和时间倒退仍会拒绝。回归使用该次任务脱敏后的真实词时间记录，
并检查缓存重新解析不会额外调用配音接口或改写音频、原始时间证据。
原失败任务及服务器产物全部保留，未恢复或改写为成功；后续可新建同主题任务。

新版本同时提供公共停止按钮、全站停止状态同步和进程清理后的任务名额释放。
代码在本地修改，上传服务器后构建 Docker 镜像；本次复用固定基础镜像
`knowmotion:2026-11-15-concurrency4`，在服务器编译前端并打包更新的应用层，
再切换运行容器。旧镜像保留为 `knowmotion:before-stop-release`，持久化数据目录未变。

候选 Linux 镜像中共 **64 项回归通过**，涵盖真实独立进程停止、脱离进程组的后代清理、
重启恢复、清理失败保留名额、默认 worker 启动、公共 API、配音解析与分镜并发。
隔离浏览器检查覆盖确认/取消停止、共享状态、保留草稿、409 竞争处理和移动端布局。
这些是软件与部署验证；本次没有额外生成完整视频，不作为新的成片验收记录。

## 2026-11-15 首次部署与视频验收记录

- 网站：<http://103.97.178.177/>；工作台：<http://103.97.178.177/workspace>。
- 目录：`/opt/knowmotion`；首次验收固定镜像标签 `knowmotion:2026-11-15-public-v2`。
- 首次验收镜像 ID：`sha256:09dc98c10532d940d1d7a23c2ef85956e1ede3045baf7f300872f87f1989f6ce`。
- 应用和 Nginx 已配置自动重启；SQLite 与视频输出使用主机持久化目录。
- 首次部署仅提供 HTTP，后续 HTTPS 配置见上节。

全新真实任务 `c77111db-9ee9-4e3b-98f0-b5cf05b7d547` 生成《导数的几何意义》，
四个场景、49.067 秒，使用 `deepseek-ai/DeepSeek-V4.1-Flash` 与 MiniMax `speech-2.8-turbo`。
通过公开 API 提交后，由项目 Agent 完成研究、讲稿和分镜，再执行真实配音与渲染；
随后运行 `scripts/verify_live.py --inspect`，`live_acceptance.json` 的九项检查均为 true。
[查看成片](http://103.97.178.177/jobs/c77111db-9ee9-4e3b-98f0-b5cf05b7d547/video)。

原始 `model_calls.json`、`live_acceptance.json`、`media_verification.json` 和所有任务产物
保存在服务器 `outputs/c77111db-9ee9-4e3b-98f0-b5cf05b7d547/`。
首轮部署发现 Wikipedia 请求标识缺少项目联系地址以及 Linux `pdflatex` 符号链接调用问题，
均修复通用代码并构建新镜像后创建新任务；旧失败记录和产物保留，未改写为验收通过。

公网实测第二次并发提交返回 409，独立匿名浏览器共享当前任务并禁用生成/重试按钮，
任务结束后共享状态恢复空闲；MP4 Range 请求返回 206。
前端构建、公共 API 针对性回归、研究来源回归与 Linux LaTeX 16 项回归通过。
这不等于全仓测试全部通过：较宽的规划测试中仍有两个旧数学 fixture 缺少新版动画协议标记，
与本次部署修复无关；它们未被用作真实成片验收依据。

## 共享网站行为

- 不需要注册、登录或浏览器令牌，访问者共享任务列表、当前制作进度和已完成视频。
- 全站同时只接收一个制作任务，活动任务存在时禁止创建或恢复另一个任务；服务端也会拒绝绕过按钮的并发提交。
- 任意访客可在当前任务点击“停止制作”，确认后全站同步显示“正在停止”。后台终止该任务及其渲染子进程，确认清理完成后才允许提交下一个主题；输入草稿保留。
- 停止通过 `POST /jobs/{id}/cancel` 发起，状态依次为 `cancelling`、`cancelled`。重复停止请求安全；已停止任务不会在重启后自动继续，也不提供恢复入口。
- 本地 worker 使用独立子进程执行每次任务。停止期间若无法确认进程清理，继续锁定生成名额；服务重启时先依据持久化的进程身份记录清理，再开放提交。
- 生产环境使用一个 API 进程和一个本地任务 worker。不要增加 Uvicorn workers 或应用副本数。
- 公网模式不开放模型配置、删除任务和任意产物下载接口；配置由服务器上的 `.env.production` 管理。
- `data/` 保存 SQLite 数据库和 LaTeX 缓存，`outputs/` 保存任务证据、音频、视频和执行记录。重建容器不会删除这些目录。

## 构建与启动

在服务器的项目目录（本次部署采用 `/opt/knowmotion`）创建 `.env.production`，
填入项目实际使用的文本和 MiniMax 配音配置。不要把密钥写入 Dockerfile、Git 或镜像构建参数。
这份文件由 Compose 在运行时读取，不进入镜像；权限应为 `600`。

```dotenv
MODEL_BASE_URL=https://your-compatible-model-api.example/v1
MODEL_NAME=your-configured-model
MODEL_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.cn
MINIMAX_MODEL=speech-2.8-turbo
MINIMAX_VOICE_ID=Chinese (Mandarin)_Gentle_Youth
MINIMAX_API_KEY=
TTS_ENABLED=true
```

Compose 强制使用 Linux 工具和字体路径，避免本机 `.env` 中的 Windows 路径影响部署。
历史视频保留随项目打包的思源宋体 Heavy；背景音乐使用 `assets/audio/vibe-bgm.m4a`、增益 `0.30`，
画面与人声统一在合成时变为 `1.15` 倍速，TTS 本身仍为 `1` 倍速。

```bash
cd /opt/knowmotion
chmod 600 .env.production
mkdir -p data outputs
# 全新服务器首次签发证书时，先使用 HTTP 引导配置。
apt-get install -y certbot
mkdir -p /etc/letsencrypt /var/lib/letsencrypt
cp deploy/nginx.conf deploy/nginx.https.conf
cp deploy/nginx.bootstrap.conf deploy/nginx.conf
docker compose -f docker-compose.production.yml build app
docker compose -f docker-compose.production.yml up -d --no-build
certbot certonly --webroot --webroot-path /var/lib/letsencrypt \
  --domain knowmotion.gragonapi.com --cert-name knowmotion.gragonapi.com \
  --agree-tos --register-unsafely-without-email --non-interactive
cp deploy/nginx.https.conf deploy/nginx.conf
docker compose -f docker-compose.production.yml exec -T web nginx -t
docker compose -f docker-compose.production.yml exec -T web nginx -s reload
install -m 0755 deploy/renew-certificate-hook.sh /etc/letsencrypt/renewal-hooks/deploy/knowmotion.sh
systemctl enable --now certbot.timer
docker compose -f docker-compose.production.yml ps
curl --fail https://knowmotion.gragonapi.com/health
curl --fail https://knowmotion.gragonapi.com/ui-config
```

默认访问 `https://knowmotion.gragonapi.com/`，公网需开放 TCP 80 和 443；应用的 8000 端口仅在 Docker 网络内可见。
如果服务器的 80 端口已有服务，可用 `PUBLIC_HTTP_PORT=8080` 设置网关端口，
或者将已有反向代理连接至应用；不能直接让两个服务抢占同一个端口。

前端每次随应用镜像重新构建。更新版本时先等当前任务结束，然后重新构建、启动：

```bash
docker compose -f docker-compose.production.yml build app
docker compose -f docker-compose.production.yml up -d --no-build
docker compose -f docker-compose.production.yml logs --tail=100 app
```

`.env.production` 中的配置更新需要重新创建应用容器，单纯 `restart` 不会读取新的环境变量。
任务执行过程中重启可能中断正在进行的外部调用或渲染，因此应在共享状态显示空闲时更新。
备份时先停止服务，再同时备份 `data/`、`outputs/` 和受限保存的 `.env.production`，完成后启动服务；
不要删除这些目录，也不要把包含密钥的备份公开。

## Cloudflare 域名与证书维护

在 `gragonapi.com` 的 DNS 页面使用：

| 类型 | 名称 | IPv4 地址 | 代理状态 |
|---|---|---|---|
| A | `knowmotion` | `103.97.178.177` | Proxied（橙云） |

DNS 的 A 记录填写 IP 地址，不包含 `http://` 或 `:端口`。网关监听标准 HTTP 80 与 HTTPS 443，
访问 `https://knowmotion.gragonapi.com/`。Nginx 已包含这个域名。
[Cloudflare DNS 记录说明](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/)

源站已安装有效 Let's Encrypt 证书，可使用 Cloudflare **Full (strict)**。
不要使用 Flexible：源站对域名的 HTTP 请求跳转 HTTPS，该模式可能产生重定向循环。
[Cloudflare Full (strict) 要求](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/)

Cloudflare 支持代理 HTTP 80 和 HTTPS 443。若改用其他端口，需要核对支持列表；
DNS 记录本身不承担端口转发。
[Cloudflare 代理端口列表](https://developers.cloudflare.com/fundamentals/reference/network-ports/)

证书维护检查：

```bash
systemctl status certbot.timer
certbot certificates
certbot renew --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

保留 HTTP 80 端口及 ACME 验证路径，续期依赖这个入口。

## 验证范围

健康检查、前端构建、并发互斥测试只能证明部署与软件行为，不能标成真实视频验收通过。
需要验收实际视频时，在容器内提交新主题，并使用现有真实模型与完整 Agent 管线：

```bash
docker compose -f docker-compose.production.yml exec app python scripts/verify_live.py --topic "微积分的本质"
# 历史导演独立正式验收：
docker compose -f docker-compose.production.yml exec app python scripts/verify_history.py --topic "你的历史主题"
```

这些 CLI 验收命令不经过公开网页的任务提交入口。执行时先暂停公网提交或在隔离的输出目录进行，
避免与网站正在制作的任务竞争资源。保留各次 `model_calls.json` 和 `live_acceptance.json`，
不得用演示片或手写讲稿代替真实验收。
