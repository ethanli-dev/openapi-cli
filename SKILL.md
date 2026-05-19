---
name: openapi-cli
description: 基于 OpenAPI Spec 的通用 API 命令行调用工具
when_to_use: 用户提到 OpenAPI、Swagger、调用 API 接口、openapi-cli、或在提供了 OpenAPI 规范 URL 的情况下需要测试 API 接口时使用
permissions:
  - allow:
      - Read: openapi-cli.py 文件或通过 python openapi-cli.py 命令执行脚本
      - Edit: 临时生成的参数文件 (如 body.json)
---

# OpenAPI CLI

## 功能概述

`openapi-cli.py` 是一个基于 OpenAPI/Swagger 规范的 API 通用调用脚本，通过解析 OpenAPI Spec（支持 Swagger 2.0 和 OpenAPI
3.x），提供以下功能：

- **自动调用 API**：根据 HTTP 方法、路径和参数，直接调用真实 API 接口，无需手动拼写请求
- **参数自动补全**：根据 Spec 定义，自动识别 Query、Path、Body 参数，用户只需按需提供参数值
- **OAuth2 客户端凭证自动管理**：支持 Client Credentials 模式，自动获取、缓存和刷新 Token
- **多格式请求体支持**：支持 JSON 格式，可从文件读取 (`--data @file.json`)
- **表格输出美化**：自动检测并使用 `tabulate` 库美化输出
- **Spec 本地缓存**：自动缓存 Spec 文件，减少重复拉取
- **Schema 查看**：支持查看 Definitions 或 Schemas 定义

## 触发关键词

以下场景应触发此 Skill：

- 用户提到 “OpenAPI CLI”、“openapi-cli”
- 用户提供了 OpenAPI/Swagger Spec 的 URL，并希望调用 API
- 用户提到 “解析 Swagger 文档调用接口”
- 用户提供 API 服务器的 base URL，并需要测试接口
- 用户有 `.json` 或 `.yaml` 的 OpenAPI 定义文件，希望生成调用命令

**示例触发语句：**

- “我有个 OpenAPI Spec，地址是 `https://api.example.com/v2/api-docs`，帮我调用 `/user/list` 接口”
- “用 openapi-cli 测试一下 POST `/user/save`，参数是 `{"name":"张三"}`”
- “帮我列出这个 API 里所有的接口路径”
- “查看一下 userDTO 这个 schema 的结构”

## 使用方法

### 0. 前置准备

确保已安装依赖：

```bash
# 安装 Python 依赖 (requests + tabulate)
pip install requests tabulate
```

### 1. 基础配置（使用环境变量）

```base
# 设置 Spec URL（OpenAPI 规范地址，必需）
export OPENAPI_SPEC_URL="https://api.example.com/v2/api-docs"

# 设置 Base URL（API 请求的服务器地址，必需）
export OPENAPI_BASE_URL="https://api.example.com"

# 如需 OAuth2 认证（可选）
export OPENAPI_OAUTH_URL="https://sso.example.com/oauth/token"
export OPENAPI_CLIENT_ID="your_client_id"
export OPENAPI_CLIENT_SECRET="your_client_secret"

# 安全提醒：通过环境变量传递敏感信息，不要在命令行中直接暴露 Token。
```

### 2. 核心命令

**命令语法**

```base
python openapi-cli.py METHOD PATH [OPTIONS]

# 可选选项：
#   -p, --param KEY=VAL       : 设置请求参数（支持 Query/Path/Header）
#   -d, --data JSON           : 设置请求体 JSON（支持字符串或 @file.json）
#   -a, --all                 : 返回完整响应 JSON（不启用表格美化）
#   -c, --cols FIELD1 FIELD2  : 指定表格输出字段
#   -f, --format FORMAT       : 输出格式（json/table，默认自动判断）
```

**参数传递规则**

- Query 参数：默认使用 -p 传递
- Path 参数：用 {param} 占位符形式，并在 -p 中传递值。例如：/user/{id} -p id=123
- Body 参数：通过 -d 传递 JSON 字符串，或使用 @filename.json 从文件读取
- Header 参数：若 Spec 中定义了自定义 Header，同样使用 -p 传递

**核心原则**：用户只需关心参数值，脚本会根据 Spec 自动将 -p 中的参数分配到 Query、Path、Header 的对应位置。

##### 示例

**获取列表（Query 参数）**

```base
python openapi-cli.py POST /user/list -p pageSize=10 -p pageNum=1
```

**带 Path 参数**

```base
python openapi-cli.py GET /user/{id} -p id=10001
```

**发送请求体（JSON）**

```base
python openapi-cli.py POST /user/save --data '{"name":"张三","email":"zhangsan@example.com"}'
```

**从文件读取请求体**

```base
python openapi-cli.py POST /user/save --data @body.json
```

**表格输出（部分字段）**

```base
python openapi-cli.py POST /user/list -p pageSize=10 --all --cols id nickName realName
```

### 3. 辅助命令

**列出所有 API 路径**

```base
python openapi-cli.py list-paths [--filter 关键词]
```

**查看某个接口的详细定义**

```base
python openapi-cli.py describe METHOD PATH

# 示例：python openapi-cli.py describe POST /user/list
```

**查看某个 Schema 定义**

```base
python openapi-cli.py schema <定义名称>
```

**刷新 Spec 缓存**

```base
python openapi-cli.py refresh
```

### 4. 访问策略管理（可选）

为更细粒度的请求控制，脚本支持通过 .openapi_policy.json 文件配置访问策略：

```base
python openapi-cli.py policy show      # 查看当前策略
python openapi-cli.py policy init      # 生成策略模板
```

### 5. 输出控制

- **默认输出：** 若返回数据为数组且安装了 tabulate，自动以表格形式展示
- **完整 JSON 输出：** 使用 --all 或设置 --format json 获取原始 JSON 响应
- **指定输出字段：** 使用 --cols 仅显示部分字段，适用于 API 返回字段过多时简化输出

### 故障排查

| 问题               | 症状/错误信息                            | 解决方法                                                                                 |
| :----------------- | :--------------------------------------- | :--------------------------------------------------------------------------------------- |
| **缺少依赖库**     | `❌ 需要 requests: pip install requests` | 安装所需依赖：<br>`pip install requests tabulate`                                        |
| **环境变量未配置** | `Error: 未配置 OPENAPI_SPEC_URL`         | 检查并设置环境变量：<br>`echo $OPENAPI_SPEC_URL`<br>`export OPENAPI_SPEC_URL="your_url"` |
| **认证失败**       | `401 Unauthorized`                       | 1. 检查 OAuth 配置是否正确<br>2. 确认 Token 未过期<br>3. 验证 API Key 或凭证             |
