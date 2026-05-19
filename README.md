# OpenAPI CLI

基于 OpenAPI/Swagger 规范的通用 API 命令行调用工具。

给一个 Swagger 文档地址，就能像调本地函数一样调远程 API — 不用手写 curl、不用管鉴权、不用拼参数。

---

## 快速开始

### 1. 安装依赖

```bash
pip install requests tabulate
```

### 2. 配置环境变量

```bash
export OPENAPI_SPEC_URL="https://api.example.com/v2/api-docs"
export OPENAPI_BASE_URL="https://api.example.com"

# OAuth2 客户端凭证（可选）
export OPENAPI_OAUTH_URL="https://auth.example.com/oauth/token"
export OPENAPI_CLIENT_ID="your_client_id"
export OPENAPI_CLIENT_SECRET="your_client_secret"
```

### 3. 开调

```bash
python openapi-cli.py POST /repairOrder/myList -d '{"pageIndex":1,"pageSize":10}'
```

---

## 命令一览

### 核心调用

```bash
python openapi-cli.py METHOD PATH [OPTIONS]
```

| 选项 | 说明 | 示例 |
|---|---|---|
| `-p, --param KEY=VAL` | Query/Path/Header 参数 | `-p pageSize=10` |
| `-d, --data JSON` | 请求体（JSON 或 @file.json） | `-d '{"name":"张三"}'` |
| `-a, --all` | 返回完整 JSON 响应 | |
| `-c, --cols` | 仅显示指定列 | `--cols id name status` |
| `-f, --format` | 输出格式：json / table | |

### 辅助命令

```bash
# 列出所有接口
python openapi-cli.py list-paths [--filter 关键词]

# 查看接口详情（参数、返回值）
python openapi-cli.py describe METHOD PATH

# 查看 Schema/Model 定义
python openapi-cli.py schema SchemaName

# 刷新 Spec 缓存
python openapi-cli.py refresh
```

### 访问策略

```bash
# 查看当前策略
python openapi-cli.py policy show

# 生成策略模板
python openapi-cli.py policy init
```

策略文件 `.openapi_policy.json` 示例（只读策略）：

```json
{
  "deny_methods": ["DELETE", "PUT", "PATCH"],
  "deny_paths": [
    "POST /order/audit",
    "POST /pay/*"
  ]
}
```

策略在**本地拦截**，不会发出请求，安全可靠。

---

## 使用示例

### GET 请求

```bash
python openapi-cli.py GET /user/{id} -p id=10001
```

### POST + JSON Body

```bash
python openapi-cli.py POST /user/save -d '{"name":"张三","email":"zhangsan@example.com"}'
```

### 从文件读取 Body

```bash
python openapi-cli.py POST /order/import -d @body.json
```

### 表格美化 + 选列

```bash
python openapi-cli.py POST /repairOrder/myList \
  -d '{"orderStateList":[1,2,3],"pageIndex":1,"pageSize":20}' \
  --cols id orderNo orderStateName flyerName createAt
```

---

## 特性

- ✅ **Swagger 2.0 / OpenAPI 3.x** 双兼容
- ✅ **参数自动分配** — 不用管 Query / Path / Body，脚本自动处理
- ✅ **OAuth2 Client Credentials** — Token 自动获取、缓存、刷新
- ✅ **Spec 本地缓存** — 24 小时有效期，减少重复拉取
- ✅ **表格输出** — 数组自动美化，可选列
- ✅ **访问策略** — 本地拦截危险操作，防误触
- ✅ **JSON / 文件 请求体** — 支持 `@{filename}` 从文件读取

---

## 故障排查

| 问题 | 解决 |
|---|---|
| `❌ 需要 requests` | `pip install requests tabulate` |
| `未配置 OPENAPI_SPEC_URL` | 检查环境变量是否 export |
| `Spec 无效` | 确认 Spec URL 可访问，是否需要鉴权 |
| `401 Unauthorized` | 检查 OAuth 配置（`OAUTH_URL`、`CLIENT_ID`、`CLIENT_SECRET`） |
| 🚫 拒绝访问 | 检查策略配置 `policy show`，或在策略文件中放行 |
| `(无数据)` | 查询条件可能过严，或当前用户无数据权限 |

---

## 文件结构

```
skills/openapi-cli/
├── SKILL.md                          # AI Agent 技能描述
├── README.md                         # 本文件
└── scripts/
    ├── openapi-cli.py                # 主脚本
    ├── .openapi_spec.json            # Spec 缓存（自动生成）
    ├── .openapi_token.json           # OAuth Token 缓存（自动生成）
    └── .openapi_policy.json          # 访问策略（手动配置）
```