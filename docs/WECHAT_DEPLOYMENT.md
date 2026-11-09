# Listingo 腾讯云部署与验收指南

发布来源为 `codex/wechat-pay-launch`，基线为 `zlq@f5ddaf3`。首次上线顺序为 **准备生产配置 → 部署及 HTTPS → 短信 → 微信登录 → 微信支付 → OCR 和真实生成 → 对外开放**。

## 1. 准备生产配置

在腾讯云 Linux 服务器使用专用项目目录。若服务器已有仓库，进入原目录并先检查旧启动脚本、当前 Compose 项目名及数据目录。更新既有服务时继续用同一个 Compose 项目和数据目录，避免指向新的 Redis 卷或覆盖已有文件。

```bash
# 只有服务器上还没有这个仓库时才执行 clone。私有仓库使用已有 GitHub 访问凭据。
git clone https://github.com/kyrieljy/Listingo.git listingo
cd listingo
git fetch origin
git log -1 --oneline origin/codex/wechat-pay-launch
# 部署前确认显示的是准备发布的提交。此操作固定在该提交上。
git checkout --detach origin/codex/wechat-pay-launch
git rev-parse HEAD
umask 077
test -f .env.production || cp .env.example .env.production
mkdir -p secrets
chmod 700 secrets
chmod 600 .env.production
```

在服务器上用编辑器填写 `.env.production`。模板可作为配置项清单。本地 `.env.wechat.local` 中的凭据可以按需录入，Linux 容器内的文件路径使用下表中的值。

| 变量 | 生产填写方式 |
| --- | --- |
| `LISTINGO_ENV_FILE` | `.env.production`。使用 Compose 时同时传 `--env-file .env.production`，分别用于容器环境和 Compose 插值。 |
| `LISTINGO_DATABASE_URL` | 独立 PostgreSQL 库和账号，例如 `postgresql://listingo:<URL编码后的密码>@host.docker.internal:5432/listingo`。远程数据库换成私网地址。 |
| `LISTINGO_REDIS_URL`、`LISTINGO_STORAGE_BACKEND` | 沿用模板的 `redis://redis:6379/0` 和 `redis`。Redis 由 Compose 启动并使用持久卷。 |
| `LISTINGO_PRODUCTION`、`LISTINGO_TESTING`、`LISTINGO_COOKIE_SECURE` | 分别为 `true`、`false`、`true`。移除已有环境中的 `LISTINGO_DEBUG_SMS_CODE`。 |
| `LISTINGO_PUBLIC_ASSET_BASE_URL`、`LISTINGO_CORS_ORIGINS` | 两者均为 `https://listingo.net`。 |
| `LISTINGO_PORT`、`LISTINGO_DATA_DIR`、`LISTINGO_TRUSTED_PROXIES` | 沿用模板的 `8000`、`/app/data`、`172.30.87.11`。 |
| `LISTINGO_BOOTSTRAP_ADMIN_PHONE` | 可收短信的专用管理员手机号。启动时用于同步 `admin` 账号，后续发布保留原值。 |
| `LISTINGO_ICP_NUMBER`、`LISTINGO_SUPPORT_CONTACT` | 实际备案号及客服联系方式。 |
| `LISTINGO_GLOBAL_DRY_RUN` | 首次为 `true`，模型配置和联调准备好后切换。 |
| `LISTINGO_WECHAT_LOGIN_ENABLED`、`LISTINGO_WECHAT_PAY_ENABLED` | 首次均为 `false`。在 HTTPS 和短信通过后分开启用。 |

微信配置可以先留空，准备启用时补齐。以下两套 AppID 分别来自已获批微信登录权限的网站应用，以及已关联商户号的服务号。

| 用途 | 变量 | 值或来源 |
| --- | --- | --- |
| 登录 | `LISTINGO_WECHAT_LOGIN_APP_ID`、`LISTINGO_WECHAT_LOGIN_APP_SECRET` | 微信开放平台网站应用的 AppID 和 AppSecret。 |
| 登录 | `LISTINGO_WECHAT_LOGIN_CALLBACK_URL` | `https://listingo.net/api/v1/auth/wechat/callback` |
| 支付 | `LISTINGO_WECHAT_MCHID`、`LISTINGO_WECHAT_APPID` | 微信支付商户号、已绑定的服务号 AppID。 |
| 支付 | `LISTINGO_WECHAT_API_V3_KEY`、`LISTINGO_WECHAT_MERCHANT_SERIAL` | 商户平台 APIv3 密钥、与商户私钥对应的商户 API 证书序列号。 |
| 支付 | `LISTINGO_WECHAT_PRIVATE_KEY_PATH` | `/run/secrets/listingo/apiclient_key.pem` |
| 支付 | `LISTINGO_WECHAT_PUBLIC_KEY_ID`、`LISTINGO_WECHAT_PUBLIC_KEY_PATH` | 商户平台 `PUB_KEY_ID_` 开头的公钥 ID，以及 `/run/secrets/listingo/wechatpay_public.pem`。 |
| 支付 | `LISTINGO_WECHAT_NOTIFY_URL` | `https://listingo.net/api/v1/payments/wechat/notify` |

把两份 PEM 文件通过 SSH 安全传到项目下的 `secrets/apiclient_key.pem` 和 `secrets/wechatpay_public.pem`，在服务器执行 `chmod 600 secrets/apiclient_key.pem secrets/wechatpay_public.pem`。Compose 会将 `secrets/` 只读挂载到 `/run/secrets/listingo/`。`.env.production`、PEM 和运行时数据留在服务器私有目录。保留 `data/.secret_key`，数据库中已加密的短信和模型凭据依赖它解密。

## 支付行为

- 一次购买套餐或补豆包；不自动扣款，有效付费订阅期间不支持购买其他套餐或提前续费。
- 套餐周期沿用现有业务：月付 31 天、年付 365 天，从权益发放时开始。补豆包沿用当前订阅到期时间；无订阅时为到账后 30 天。
- 价格、币种、商品名称和豆子数在下单时快照保存。扫码、回调、补偿查单共用订单号。
- `/subscription/orders` 创建订单；`POST /subscription/orders/{id}/wechat-native` 获取二维码；`GET /subscription/orders/{id}` 读取状态。均以 `/api/v1` 为前缀并要求用户登录。
- `/payments/wechat/notify` 接收通知，先验证原始报文签名，再用 APIv3 密钥解密。检查商户、AppID、金额、币种、订单及交易状态。
- 用户行、订单行加锁，支付事实及权益在同一 PostgreSQL 事务中提交；微信交易号、发放来源唯一。数据库提交成功后才返回 204。
- 前端每 3 秒查询本地订单状态；后端默认每 60 秒扫描待确认订单，每批最多 50 个。浏览器关闭或进程重启不会丢失订单。
- 超时先查单再关单；支付与关单竞争时重新查单。支付时间在有效期内的延迟通知可正常到账，超时支付或重复套餐收款进入 `manual_review`。
- `manual_review` 不自动发放，不自动退款，必须由运营跟进。日志事件为 `payment_manual_review`、`payment_reconcile_failed`，应接入云日志告警。
- 模拟支付只在 `testing=true` 且微信支付未启用时可用，生产始终禁用。真实收款不能使用测试模式。

## 2. 检查服务器并发布

使用有 sudo 权限的 SSH 账号，安装 Git、Docker Engine/Compose 插件、Nginx、Certbot 和 curl。只开放必要的 SSH 来源、80、443。

- DNS A 记录指向腾讯云公网 IPv4。无可用 IPv6 时不要添加 AAAA。
- 复用已有 PostgreSQL，为应用建立专用数据库和账号。迁移需要该库的建表/改表权限。
- `.env.production` 的数据库 URL 使用 `postgresql://`，密码中的保留字符需要 URL 编码。示例 `host.docker.internal` 指同一宿主机；远程数据库改用私网地址。
- 如果数据库在宿主机，调整 PostgreSQL 监听地址及 `pg_hba.conf`，仅允许 Compose 网段和应用账号，不将 5432 开放公网。
- Compose 固定网段 `172.30.87.0/24`，前端固定 `.11`，其余容器动态分配地址。先确认不与 VPC/VPN/其他容器网络重叠；变更时同步修改 `LISTINGO_TRUSTED_PROXIES`。
- Nginx 宿主机只代理 `127.0.0.1:5173`。内部 Nginx 保留转发头，Uvicorn 只信任前端容器地址；公网输入的转发头由外层 Nginx 覆盖。

在服务器项目目录运行仓库内的部署脚本。

```bash
bash scripts/deploy.sh
curl --fail http://127.0.0.1:5173/api/v1/health
```

脚本要求干净的 Git 工作树，负责校验 Compose、构建镜像、启动 Redis、执行 Alembic 迁移、启动应用及检查健康接口。已由脚本发布过的实例会在迁移前停应用并备份。若现有服务是旧脚本部署且没有 `data/.release`，先安排维护窗口、暂停写入并手动备份，再迁移。

首次签发证书时，先确认 DNS 和 80 端口生效，再按顺序执行以下命令。已有有效证书时，直接检查并应用 HTTPS 站点配置。若原站点配置有自定义规则，先合并规则，确保同一个域名只有一套生效的 server 配置，并保留新版对微信登录回调访问日志的处理。

```bash
sudo mkdir -p /var/www/letsencrypt
sudo cp deploy/nginx/bootstrap.conf /etc/nginx/conf.d/listingo.conf
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt -d listingo.net
sudo cp deploy/nginx/listingo.conf /etc/nginx/conf.d/listingo.conf
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
curl --fail https://listingo.net/api/v1/health
```

清理或停用冲突的默认 Nginx 站点，配置证书续期后的 Nginx reload deploy hook，并确认 Certbot 定时任务实际启用。

## 3. 初始化短信和管理员

首次开通短信时，在服务器 SSH 终端交互执行以下命令。准备阿里云短信或号码认证服务的 AccessKey、获批签名、登录模板和管理员验证模板。脚本隐藏 AccessKey 输入，并将凭据加密保存。已有短信配置可先测试现有配置。

```bash
export LISTINGO_ENV_FILE=.env.production
docker compose --env-file .env.production exec backend python -m backend.app.bootstrap_sms
```

打开 [运营后台](https://listingo.net/admin)，使用 `LISTINGO_BOOTSTRAP_ADMIN_PHONE` 接收真实验证码登录。在「短信服务」核对服务已启用、调试模式关闭，并完善注册、换绑手机等使用到的模板。用普通账号在 `/app` 验证短信登录，确认验证码实际送达。

## 4. 开启微信扫码登录

1. 在微信开放平台网站应用确认微信登录权限已获批，把「授权回调域」保存为 `listingo.net`。生产站点使用裸域，截图中原先的 `www.listingo.net` 需要对应调整。单独的「业务域名」可留空。 [微信网站应用登录指南](https://developers.weixin.qq.com/doc/oplatform/Website_App/WeChat_Login/Wechat_Login.html)
2. 确认网站应用的三项配置已填写，然后将 `LISTINGO_WECHAT_LOGIN_ENABLED=true`。微信登录开关在后端环境文件中。修改环境变量后执行下面的命令，使容器重新读取文件。

```bash
export LISTINGO_ENV_FILE=.env.production
docker compose --env-file .env.production up -d --no-deps --force-recreate backend
curl --fail https://listingo.net/api/v1/health
curl --fail https://listingo.net/api/v1/auth/wechat/status
```

3. 状态接口应返回 `enabled: true`。从 [生产工作台](https://listingo.net/app) 的登录弹窗直接点微信，确认出现官方二维码。首次扫码后在手机绑定弹窗勾选协议并验证手机号。分别用新手机号与已注册普通手机号测试，核对新账号创建和原账号权益保留。退出再扫码，确认直接登录。管理员仍用原登录入口。
4. 若微信显示 `redirect_uri 参数错误`，核对网站应用 AppID、开放平台实际已保存的回调域，以及 `LISTINGO_WECHAT_LOGIN_CALLBACK_URL` 的主机名。用 `https://listingo.net/app` 发起扫码，确保发起端和回调端共用同一站点的浏览器凭证。

## 5. 开启微信 Native 支付

1. 在商户平台复核 Native 已开通且服务号 AppID 已关联。填齐商户配置并确认两个 PEM 路径，然后将 `LISTINGO_WECHAT_PAY_ENABLED=true`，执行第 4 节的后端重建和健康检查命令。环境缺失、证书内容无效或回调协议错误会导致启动失败。 [Native 接入准备](https://pay.wechatpay.cn/doc/v3/merchant/4015614538) [APIv3 签名与验签](https://pay.wechatpay.cn/doc/v3/merchant/4012365342)
2. 对外开放前，在「商业化目录」准备低金额验收商品。用受限普通账号分别完成套餐和补豆包的扫码实付。在「支付订单管理」核对已支付、金额、交易号，在用户侧核对会员到期时间及豆子账本。重开页面检查权益只发放一次。另做一笔扫码付款后关闭页面的测试，稍后重新登录检查到账。
3. 验证订单到期、订阅有效期内拒绝重复购买、补豆包仍可买。真实退款按第 8 节操作。监控 `payment_manual_review` 和 `payment_reconcile_failed`，检查未决订单。轮换验签公钥前先控制新下单流量并处理未决订单，再更换 PEM、公钥 ID 并重建后端。

## 6. 检查 OCR 和真实生成

1. 进入后台「OCR 配置」。生产启动会在后台自动预热，应用健康接口可能先于 OCR 就绪。刷新页面查看「启动自动预热」及各引擎结果。默认使用 RapidOCR，先验证默认配置。若失败，查看后端日志，并根据引擎检查模型文件、网络或依赖，再点「重新预热」。保存 OCR 配置会安排新一轮自动预热。
2. 在工作台打开带有清晰文字的生成结果，使用文字编辑功能触发识别，检查文字及区域定位。每次重建后端后重新核对预热状态。
3. 在「模型配置」录入实际 Provider 地址、模型及密钥，确认配额与费用。先用 Dryrun 验证上传、任务流程和下载。管理员可在工作台选择 Live 做一单最小任务，核对任务日志、模型结果和豆子扣减。视频功能还要确认外部 Provider 能访问实际生成的公网参考图地址。准备向普通用户开放实际调用后，将 `LISTINGO_GLOBAL_DRY_RUN=false` 并重建后端。

```bash
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=150 backend
```

## 7. 备份、恢复及回退

`bash scripts/backup.sh` 使用临时 PostgreSQL 18 客户端容器生成自定义格式 dump，并归档 `data`、`secrets` 和环境文件。数据库服务端必须不高于客户端主版本；需要时通过 `LISTINGO_POSTGRES_CLIENT_IMAGE` 指定匹配镜像。

每日安排任务运行备份，随后将两个文件复制至加密异机存储，设置失败告警及保留期限。脚本只生成本地备份，不代表异机备份已完成。更新部署会停止应用后再备份；日常在线备份请避开文件清理窗口。

恢复演练必须使用独立测试数据库和独立目录：

1. 将 dump 使用 `pg_restore --no-owner --dbname=<测试连接串>` 导入空测试库；实际操作通过安全环境配置提供密码。
2. 解包文件备份到独立目录，恢复同一份 `.secret_key`，调整测试环境数据库和数据路径。
3. 禁用微信登录、微信支付及实际 Provider 调用，用受限测试环境核对用户、订单、豆子账本、上传与结果文件。
4. 记录备份时间、恢复时间和核对结果，不覆盖生产数据库。

每次发布保存 `data/.release`（Git SHA）和 `data/.schema-version`。应用启动时校验迁移版本，回退前需确认代码和数据库版本兼容。优先在当前数据库上前向修复。若必须恢复备份，先保留当前数据库及文件副本，并人工对账处理备份之后产生的付款、退款和权益变更。若历史版本的运行时密钥曾用于生产，轮换前先做受控的凭据重新加密，保留数据库与密钥的配对备份。

## 8. 退款及正式开放

后台“支付订单管理”显示微信交易号、异常原因及退款备注。运营先在微信商户平台确认全额退款成功，再登记退款单号和核对说明；系统撤销该订单剩余豆子及订阅。已使用/预留权益必须人工核对并在备注记录，接口不自动向微信发起退款，不支持部分退款。

正式开放前逐项完成：

- 普通用户真实登录，非本人订单不可查询；生产 mock-pay 返回 404。
- 用专用低金额商品分别购买套餐和补豆包，核对商户实收、订单状态、豆子和订阅。
- 重复通知仅到账一次；关网页后可到账；付款后重启可补偿查单。
- 过期未付正确关单；已付款但有异常时进入人工处理。
- 商户平台退款并在后台登记，核对剩余权益撤销。
- `/app`、`/admin` 深层刷新、短信、上传、生成、下载与外部模型访问参考图正常。
- 填写真实备案号、客服及经营主体信息，审定页面服务协议、隐私政策与退款说明。现有页面文案仅为业务说明初稿，运营需补全实际主体、服务商、数据保存及处理规则后发布。
- 云日志配置支付异常告警；配置服务器磁盘、数据库、备份和证书续期监控。
- 将 Dryrun 切换为真实生成前，核对 Provider 的实际费用、配额及密钥。

上述真实收款、外网通知、异机恢复演练和云端配置不能由本地自动化测试替代。
