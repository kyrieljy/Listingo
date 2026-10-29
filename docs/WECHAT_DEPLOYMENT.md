# 微信 Native 支付与腾讯云部署

基线：`zlq@f5ddaf3`。开发分支：`codex/wechat-pay-launch`。

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

## 商户准备

普通直连商户模式。确认 Native 已获批、AppID 类型适用且与商户号完成绑定。网站应用 AppID 不要直接假设可用。

将商户私钥保存为 `secrets/apiclient_key.pem`，微信支付公钥保存为 `secrets/wechatpay_public.pem`。商户 API 证书序列号与微信支付公钥 ID 是不同参数。

复制 `.env.example` 为 `.env.production`，填写数据库、实际管理员手机号、备案号及客服渠道。密钥和文件不进 Git。私钥目录只读挂载，`data/.secret_key` 是 Provider/短信凭据的运行时加密密钥，需随数据备份。

本次停止跟踪历史误提交的测试产物及 `backend/data/.secret_key`，但不会改写 Git 历史。若历史密钥曾用于生产，请核对使用范围，通过受控迁移重新加密现有凭据，再轮换相关外部凭据；不要直接删除在用 `.secret_key`，否则原有加密配置将无法解密。

初次部署先保持 `LISTINGO_WECHAT_PAY_ENABLED=false`、`LISTINGO_GLOBAL_DRY_RUN=true`。完成商户参数及 Native 绑定后再打开支付开关。回调地址固定为：

`https://listingo.net/api/v1/payments/wechat/notify`

开启支付时缺少密钥、无效密钥或错误回调协议会阻止启动。微信公钥轮换时先停用新下单，处理未决订单，再更换配置重启并做签名联调；此版本固定单个验签公钥 ID，不自动下载平台证书。

官方依据：

- [Native 接入准备](https://pay.wechatpay.cn/doc/v3/merchant/4015614538)
- [Native 下单](https://pay.wechatpay.cn/doc/v3/merchant/4012791877)
- [APIv3 签名与验签](https://pay.wechatpay.cn/doc/v3/merchant/4012365342)

## 服务器前置检查

使用有 sudo 权限的 SSH 账号，安装 Git、Docker Engine/Compose 插件、Nginx、Certbot 和 curl。只开放必要的 SSH 来源、80、443。

- DNS A 记录指向腾讯云公网 IPv4。无可用 IPv6 时不要添加 AAAA。
- 复用已有 PostgreSQL，为应用建立专用数据库和账号。迁移需要该库的建表/改表权限。
- `.env.production` 的数据库 URL 使用 `postgresql://`，密码中的保留字符需要 URL 编码。示例 `host.docker.internal` 指同一宿主机；远程数据库改用私网地址。
- 如果数据库在宿主机，调整 PostgreSQL 监听地址及 `pg_hba.conf`，仅允许 Compose 网段和应用账号，不将 5432 开放公网。
- Compose 固定网段 `172.30.87.0/24`，前端固定 `.11`，其余容器动态分配地址。先确认不与 VPC/VPN/其他容器网络重叠；变更时同步修改 `LISTINGO_TRUSTED_PROXIES`。
- Nginx 宿主机只代理 `127.0.0.1:5173`。内部 Nginx 保留转发头，Uvicorn 只信任前端容器地址；公网输入的转发头由外层 Nginx 覆盖。

## 首次发布

以下操作在服务器项目目录执行。先审查服务器已有的一键启动脚本，避免与新脚本重复启动端口或覆盖数据。

```bash
git fetch origin
git checkout <已审查的发布提交SHA>
cp .env.example .env.production
mkdir -p secrets
chmod 700 secrets
chmod 600 .env.production
# 编辑配置并上传密钥，不要在终端历史中粘贴密钥。
bash scripts/deploy.sh
```

脚本会校验 Compose、构建、启动 Redis、执行迁移、启动应用并检查内部健康接口；拒绝未提交的工作树。它不执行 git pull、DNS、防火墙、TLS 签发或自动修改宿主机 Nginx。注意首次复制命令只执行一次，后续发布保留原配置。

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

先配置真实短信再开放用户登录。新生产库不会启用调试短信；现有库即使误开 debug_mode，生产配置也拒绝返回验证码。在服务器 SSH 终端执行 `LISTINGO_ENV_FILE=.env.production docker compose --env-file .env.production run --rm backend python -m backend.app.bootstrap_sms`，交互录入获批的短信签名、模板与凭据（密钥隐藏输入），随后测试短信登录，再在后台完善其他短信模板。不得为了配置短信临时将公网实例切到 testing 模式。

生产管理员手机号由 `LISTINGO_BOOTSTRAP_ADMIN_PHONE` 指定，不使用源码历史手机号；启动会按该手机号同步用户名为 admin 的账号，请勿随意改动。

## 备份、恢复及回退

`bash scripts/backup.sh` 使用临时 PostgreSQL 18 客户端容器生成自定义格式 dump，并归档 `data`、`secrets` 和环境文件。数据库服务端必须不高于客户端主版本；需要时通过 `LISTINGO_POSTGRES_CLIENT_IMAGE` 指定匹配镜像。

每日安排任务运行备份，随后将两个文件复制至加密异机存储，设置失败告警及保留期限。脚本只生成本地备份，不代表异机备份已完成。更新部署会停止应用后再备份；日常在线备份请避开文件清理窗口。

恢复演练必须使用独立测试数据库和独立目录：

1. 将 dump 使用 `pg_restore --no-owner --dbname=<测试连接串>` 导入空测试库；实际操作通过安全环境配置提供密码。
2. 解包文件备份到独立目录，恢复同一份 `.secret_key`，调整测试环境数据库和数据路径。
3. 禁用微信支付及实际 Provider 调用，用受限测试环境核对用户、订单、豆子账本、上传与结果文件。
4. 记录备份时间、恢复时间和核对结果，不覆盖生产数据库。

每次发布保存 `data/.release`（Git SHA）和 `data/.schema-version`。此次迁移只增加可空支付字段，保留旧字段；优先保留新版数据库并回退兼容应用代码。不要自动执行 Alembic downgrade，避免丢失微信交易号和审计信息。

## 退款及正式开放

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
