"""
OpenAPI CLI（基于 OpenAPI Spec 自举）
==================================================
用法:
    python openapi-cli.py METHOD PATH [--param value ...] [--data '{}'|@file.json] [--all]
    python openapi-cli.py list-paths [--filter xxx]
    python openapi-cli.py describe METHOD PATH
    python openapi-cli.py schema DEFINITION_NAME
    python openapi-cli.py refresh              # 重新拉取 spec

示例:
    python openapi-cli.py POST /user/list -p pageSize=1 -f json
    python openapi-cli.py POST /user/list -p state=2 --all --cols id nickName realName
    python openapi-cli.py POST /user/save --data @body.json
    python openapi-cli.py list-paths -k user
    python openapi-cli.py describe POST /user/list
    python openapi-cli.py schema userListDTO
    python openapi-cli.py refresh
    python openapi-cli.py policy show          # 查看当前访问策略
    python openapi-cli.py policy init          # 生成策略模板 ./.openapi_policy.json

环境变量:
    OPENAPI_BASE_URL   默认 https://api.example.com
    OPENAPI_SPEC_URL   默认 https://api.example.com/v2/api-docs

依赖: pip install requests tabulate
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

# ── 可选依赖 ──
try:
    import requests
except ImportError:
    sys.exit("❌ 需要 requests: pip install requests")

try:
    from tabulate import tabulate

    HAS_TABULATE = True
except ImportError:
    tabulate = None
    HAS_TABULATE = False

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BASE_URL = os.environ.get("OPENAPI_BASE_URL", "https://api.example.com").rstrip("/")

SPEC_URL = os.environ.get(
    "OPENAPI_SPEC_URL",
    "https://api.example.com/v2/api-docs",
)

OAUTH_URL = os.environ.get("OPENAPI_OAUTH_URL", "https://sso.example.com/oauth/token")
CLIENT_ID = os.environ.get("OPENAPI_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("OPENAPI_CLIENT_SECRET", "")

# ── 缓存/策略文件与脚本同目录 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_CACHE = _SCRIPT_DIR / ".openapi_token.json"
SPEC_CACHE = _SCRIPT_DIR / ".openapi_spec.json"
POLICY_FILE = _SCRIPT_DIR / ".openapi_policy.json"
SPEC_TTL = 86400


# ═══════════════════════════════════════════════════════════
# Token 管理
# ═══════════════════════════════════════════════════════════
class AuthManager:
    @staticmethod
    def _load_cached_token() -> str | None:
        try:
            if TOKEN_CACHE.exists():
                cache = json.loads(TOKEN_CACHE.read_text())
                if cache.get("expires_at", 0) > time.time() + 60:
                    return cache["access_token"]
        except Exception:
            pass
        return None

    @staticmethod
    def _save_token(access_token: str, expires_in: int):
        TOKEN_CACHE.write_text(
            json.dumps(
                {
                    "access_token": access_token,
                    "expires_at": int(time.time()) + expires_in,
                }
            )
        )
        TOKEN_CACHE.chmod(0o600)

    @classmethod
    def clear_cache(cls):
        """清空 token 缓存"""
        cls._save_token("", 0)

    @classmethod
    def ensure(cls) -> str:
        token = cls._load_cached_token()
        if token:
            return token
        resp = requests.get(
            OAUTH_URL,
            params={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        inner = data.get("data", data)
        token = inner["access_token"]
        cls._save_token(token, inner.get("expires_in", 3600))
        return token


# ═══════════════════════════════════════════════════════════
# Spec 管理
# ═══════════════════════════════════════════════════════════


class SpecManager:
    """拉取、缓存、查询 OpenAPI Spec."""

    def __init__(self):
        self._spec: dict | None = None

    @property
    def spec(self) -> dict:
        if self._spec is None:
            self._spec = self._load()
        return self._spec

    def _load(self) -> dict:
        # 优先读缓存
        if SPEC_CACHE.exists():
            try:
                cache = json.loads(SPEC_CACHE.read_text())
                if cache.get("_cached_at", 0) > time.time() - SPEC_TTL:
                    return cache
            except Exception:
                pass
        return self._fetch()

    def _fetch(self) -> dict:
        print(f"📥 拉取 OpenAPI Spec: {SPEC_URL}", file=sys.stderr)
        resp = requests.get(SPEC_URL, timeout=30)
        resp.raise_for_status()
        spec = resp.json()
        # 不走缓存非正常响应（如 401）
        if resp.status_code != 200 or "swagger" not in spec and "openapi" not in spec:
            sys.exit(f"❌ Spec 无效: {spec.get('message', spec)}")
        spec["_cached_at"] = int(time.time())
        SPEC_CACHE.write_text(json.dumps(spec, ensure_ascii=False))
        return spec

    def _match_path(self, template: str, path: str) -> bool:
        """将模板 /a/{b}/c 与实际 /a/123/c 匹配."""
        t_parts = template.strip("/").split("/")
        p_parts = path.strip("/").split("/")
        if len(t_parts) != len(p_parts):
            return False
        for t, p in zip(t_parts, p_parts):
            if t.startswith("{") and t.endswith("}"):
                continue  # 路径参数，匹配任意值
            if t != p:
                return False
        return True

    def refresh(self):
        self._spec = self._fetch()
        print("✅ Spec 已更新", file=sys.stderr)

    def resolve(self, method: str, path: str) -> dict | None:
        """根据 METHOD + PATH 查找 operation 对象."""
        method = method.lower()
        paths = self.spec.get("paths", {})

        # 精确匹配
        if path in paths and method in paths[path]:
            return paths[path][method]

        # 模糊匹配（带路径参数的模板如 /user/{id}）
        for template, methods in paths.items():
            if self._match_path(template, path) and method in methods:
                return methods[method]

        return None

    def list_paths(self, keyword: str | None = None) -> list[dict]:
        """列出所有 path，可选过滤."""
        result = []
        for path, methods in self.spec.get("paths", {}).items():
            for method, op in methods.items():
                if keyword and keyword.lower() not in path.lower():
                    continue
                result.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "summary": op.get("summary", ""),
                        "tags": ", ".join(op.get("tags", [])),
                    }
                )
        result.sort(key=lambda x: (x["path"], x["method"]))
        return result

    def get_definition(self, name: str) -> dict | None:
        """获取 definition/schema."""
        defs = self.spec.get("definitions", {})
        # 尝试直接匹配
        if name in defs:
            return defs[name]
        # 模糊匹配（去掉包名前缀）
        for key in defs:
            if key.endswith(f".{name}") or key == name:
                return defs[key]
        return None


# ═══════════════════════════════════════════════════════════
# 访问控制策略
# ═══════════════════════════════════════════════════════════
class AccessPolicy:
    """基于文件的访问控制：Allowlist / Tag / Method 三层过滤。

    策略文件 .openapi_policy.json：
    {
      "allow_tags": ["用户管理"],      // 只允许这些 tag 的接口（空=全部）
      "deny_methods": ["DELETE"],        // 禁止的 HTTP 方法
      "allow_paths": [                   // 精确允许（设置了就只看这个）
        "POST /user/list",
        "GET /user/detail"
      ],
      "deny_paths": [                    // 精确拒绝
        "DELETE /user/remove"
      ]
    }
    优先级：allow_paths > deny_paths > allow_tags > deny_methods
    """

    def __init__(self, policy_path: Path = POLICY_FILE):
        self.policy_path = policy_path
        self._policy: dict = {}

    def load(self):
        if not self.policy_path.exists():
            # 默认策略：排掉危险方法，放行其余
            self._policy = {"deny_methods": ["DELETE"]}
            return
        try:
            self._policy = json.loads(self.policy_path.read_text())
        except Exception as e:
            print(f"⚠️  策略文件解析失败，使用默认安全策略: {e}", file=sys.stderr)
            self._policy = {"deny_methods": ["DELETE"]}

    @property
    def is_restrictive(self) -> bool:
        """是否处于限制模式（有 allow 规则生效）."""
        return bool(self._policy.get("allow_tags") or self._policy.get("allow_paths"))

    def check(self, method: str, path: str, tags: list[str]) -> tuple[bool, str]:
        """返回 (是否放行, 原因)."""
        key = f"{method.upper()} {path}"

        # Layer 1: 精确 Allowlist（优先级最高）
        allow_paths = self._policy.get("allow_paths", [])
        if allow_paths:
            if key in allow_paths:
                return True, ""
            # 也支持通配符 path（如 "GET /user/*"）
            for pattern in allow_paths:
                if self._match(key, pattern):
                    return True, ""
            return False, f"不在 allow_paths 中（当前允许 {len(allow_paths)} 个接口）"

        # Layer 2: 精确 Blocklist
        deny_paths = self._policy.get("deny_paths", [])
        for pattern in deny_paths:
            if self._match(key, pattern):
                return False, f"在 deny_paths 中: {pattern}"

        # Layer 3: Method 过滤
        deny_methods = [m.upper() for m in self._policy.get("deny_methods", [])]
        if method.upper() in deny_methods:
            return False, f"HTTP {method.upper()} 被 deny_methods 禁止"

        # Layer 4: Tag 过滤
        allow_tags = self._policy.get("allow_tags", [])
        if allow_tags:
            if not any(t in allow_tags for t in tags):
                return False, f"tag {tags} 不在 allow_tags {allow_tags} 中"

        return True, ""

    @staticmethod
    def _match(key: str, pattern: str) -> bool:
        """pattern 支持通配符: GET /user/*"""
        if pattern == key:
            return True
        if pattern.endswith("/*"):
            prefix = pattern[:-2]  # "GET /user/"
            return key.startswith(prefix)
        return False

    def filter_paths(self, items: list[dict]) -> list[dict]:
        """过滤 list-paths 结果，隐藏无权限的接口."""
        if not self.is_restrictive:
            return items
        result = []
        for item in items:
            ok, _ = self.check(
                item["method"],
                item["path"],
                item.get("tags", "").split(", "),
            )
            if ok:
                result.append(item)
        return result

    def describe(self) -> str:
        """返回当前策略描述."""
        lines = ["📋 当前访问策略:"]
        if not self._policy:
            lines.append("  默认安全策略: 禁止 DELETE，其余放行")
            return "\n".join(lines)

        ap = self._policy.get("allow_paths")
        if ap:
            lines.append(f"  allow_paths: {len(ap)} 个")
            for p in ap[:5]:
                lines.append(f"    ✅ {p}")
            if len(ap) > 5:
                lines.append(f"    ... 及其他 {len(ap) - 5} 个")
        else:
            at = self._policy.get("allow_tags")
            if at:
                lines.append(f"  allow_tags: {at}")
            dm = self._policy.get("deny_methods")
            if dm:
                lines.append(f"  deny_methods: {dm}")
            dp = self._policy.get("deny_paths")
            if dp:
                lines.append(f"  deny_paths: {len(dp)} 个")
                for p in dp[:5]:
                    lines.append(f"    ❌ {p}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 参数解析器
# ═══════════════════════════════════════════════════════════


class ParamResolver:
    """从 operation 对象提取参数定义，并解析用户输入."""

    def __init__(self, operation: dict):
        self.operation = operation
        self.params: list[dict] = operation.get("parameters", [])

    def get_param(self, name: str) -> dict | None:
        for p in self.params:
            if p.get("name") == name:
                return p
        return None

    def list_params(self) -> list[dict]:
        return self.params

    def describe_params(self) -> str:
        """生成参数帮助文本."""
        lines = []
        for p in self.params:
            required = " (必填)" if p.get("required") else ""
            ptype = p.get("type", "string")
            desc = p.get("description", "")
            default = f" 默认={p['default']}" if "default" in p else ""
            lines.append(f"  --{p['name']}  <{ptype}>{required}{default}  {desc}")
        return "\n".join(lines)

    def build_request_args(self, user_params: dict, path: str) -> dict:
        """根据用户传入参数，构建 requests 调用参数."""
        query = {}
        headers = {}
        body = {}
        resolved_path = path
        has_body_param = any(p.get("in") == "body" for p in self.params)

        for p in self.params:
            name = p["name"]
            loc = p.get("in", "query")
            value = user_params.get(name)

            if value is None:
                if p.get("required") and not has_body_param:
                    print(f"⚠️  缺少必填参数: --{name}", file=sys.stderr)
                continue

            if loc == "query":
                query[name] = value
            elif loc == "body":
                body[name] = value
            elif loc == "path":
                resolved_path = resolved_path.replace(f"{{{name}}}", str(value))
            elif loc == "header":
                headers[name] = value

        # 如果有 body 参数定义，把 user_params 中没有在 spec 中定义的参数
        # 也一并放入 body（兼容 spec 不完备的实际 API）
        if has_body_param:
            for k, v in user_params.items():
                if not any(p["name"] == k for p in self.params):
                    body[k] = v

        return {"path": resolved_path, "query": query, "headers": headers, "body": body}


# ═══════════════════════════════════════════════════════════
# HTTP Client
# ═══════════════════════════════════════════════════════════


class APIClient:
    def __init__(self, spec: SpecManager):
        self.spec = spec
        self.auth = AuthManager()

    def _request(self, method: str, path: str, query=None, body=None, headers=None):
        base_path = self.spec.spec.get("basePath", "").rstrip("/")
        url = urljoin(BASE_URL + "/", base_path.lstrip("/") + "/" + path.lstrip("/"))
        hdrs = {
            "Authorization": f"Bearer {self.auth.ensure()}",
            "Content-Type": "application/json",
        }
        if headers:
            hdrs.update(headers)

        print(f"\n=== HTTP 请求明细 ===")
        print(f"📤 方法: {method.upper()}")
        print(f"🌐 URL: {url}")

        if query:
            print(f"🔍 查询参数: {query}")

        if body:
            print(f"📦 请求体:")
            import json

            print(json.dumps(body, ensure_ascii=False, indent=2))

        resp = requests.request(
            method=method.upper(),
            url=url,
            params=query,
            json=body,
            headers=hdrs,
            timeout=30,
        )

        if resp.status_code == 401:
            # Token 过期，刷新重试一次
            self.auth.clear_cache()  # 清缓存
            hdrs["Authorization"] = f"Bearer {self.auth.ensure()}"
            resp = requests.request(
                method=method.upper(),
                url=url,
                params=query,
                json=body,
                headers=hdrs,
                timeout=30,
            )

        resp.raise_for_status()
        data = resp.json()
        # 自动解包 {status, message, data} 外层包装
        if isinstance(data, dict) and "status" in data:
            status = data["status"]
            if status not in (200, 0):
                if status == 401:
                    self.auth.clear_cache()
                sys.exit(f"❌ API 错误 [{data.get('status')}]: {data.get('message')}")
            data = data["data"]
        return data

    def call(
        self,
        method: str,
        path: str,
        params: dict,
        body: dict | None = None,
        paginate: bool = False,
    ) -> dict:
        """执行 API 调用，支持自动分页."""
        op = self.spec.resolve(method, path)
        resolver = ParamResolver(op)
        req = resolver.build_request_args(params, path)
        # --data 显式传入的 body 优先级高于 spec 推导的 body
        merged_body = body if body is not None else req.get("body") or None
        if body and req.get("body"):
            merged_body = {**req["body"], **body}

        if not paginate:
            return self._request(
                method, req["path"], req["query"], merged_body, req["headers"]
            )

        # 全量分页
        all_rows = []
        page = 1
        page_size = params.get("pageSize", params.get("size", 200))

        while True:
            p = {**params, "pageIndex": page, "pageSize": page_size}
            req2 = resolver.build_request_args(p, path)
            # 分页循环中，分页参数必须优先，不能被用户原始 body 覆盖
            base_body = req2.get("body") or {}
            user_body = body or {}
            merged_page_body = {
                **base_body,
                **user_body,
                "pageIndex": page,
                "pageSize": page_size,
            }

            data = self._request(
                method, req2["path"], req2["query"], merged_page_body, req2["headers"]
            )
            rows = data.get("data", []) if isinstance(data, dict) else data
            if not rows:
                break
            all_rows.extend(rows)
            total = (
                data.get("totalCount", data.get("total", 0))
                if isinstance(data, dict)
                else 0
            )
            print(
                f"\r  获取第 {page} 页 ({len(all_rows)}/{total})...",
                end="",
                flush=True,
                file=sys.stderr,
            )
            if total and len(all_rows) >= total:
                break
            if len(rows) < page_size:
                break
            page += 1

        print(file=sys.stderr)
        return {"data": all_rows, "totalCount": len(all_rows), "totalPages": page}


# ═══════════════════════════════════════════════════════════
# 输出格式化
# ═══════════════════════════════════════════════════════════


class OutputFormatter:
    @staticmethod
    def table(rows: list, columns: list[str] | None = None):
        if not rows:
            print("(无数据)")
            return
        if columns is None:
            columns = list(rows[0].keys())
        if HAS_TABULATE:
            # 转为 list-of-lists 格式兼容新版 tabulate
            data = [[r.get(c, "") for c in columns] for r in rows]
            print(tabulate(data, headers=columns, tablefmt="simple"))
        else:
            for r in rows:
                print("  ".join(f"{c}={r.get(c, '')}" for c in columns))

    @staticmethod
    def json_out(data: Any):
        print(json.dumps(data, indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════
# CLI 主入口
# ═══════════════════════════════════════════════════════════


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="OpenAPI CLI（基于 OpenAPI Spec）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = p.add_subparsers(dest="command", help="子命令")

    # ── call: 通用 API 调用 ──
    call = sub.add_parser(
        "call",
        help="通用 API 调用: METHOD PATH [--params]",
        aliases=["GET", "POST", "PUT", "DELETE", "PATCH"],
    )
    call.add_argument(
        "method", nargs="?", default="GET", help="HTTP 方法 (GET/POST/PUT/DELETE/PATCH)"
    )
    call.add_argument("path", help="API 路径，如 /user/list")
    call.add_argument(
        "--params", "-p", nargs="*", default=[], help="查询参数: --param key=value ..."
    )
    call.add_argument(
        "--data", "-d", default=None, help="请求体: JSON 字符串 或 @文件.json"
    )
    call.add_argument(
        "--all", action="store_true", dest="paginate", help="自动分页获取全量数据"
    )
    call.add_argument(
        "--format", "-f", choices=["json", "table"], default="table", help="输出格式"
    )
    call.add_argument("--cols", nargs="*", default=None, help="表格显示哪些列")

    # ── list-paths ──
    lp = sub.add_parser("list-paths", help="列出所有 API 路径", aliases=["paths"])
    lp.add_argument("--filter", "-k", default=None, dest="keyword", help="按关键字过滤")
    lp.add_argument("--format", "-f", choices=["json", "table"], default="table")

    # ── describe ──
    desc = sub.add_parser(
        "describe", help="查看 API 详情（参数、响应）", aliases=["desc"]
    )
    desc.add_argument("method", help="HTTP 方法")
    desc.add_argument("path", help="API 路径")

    # ── schema ──
    sch = sub.add_parser("schema", help="查看数据模型定义")
    sch.add_argument("name", help="Definition 名称")

    # ── refresh ──
    sub.add_parser("refresh", help="重新拉取 OpenAPI Spec")

    # ── policy ──
    pol = sub.add_parser("policy", help="查看当前访问策略", aliases=["pol"])
    pol.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=["show", "init"],
        help="show=查看策略 / init=生成默认策略文件",
    )

    return p


def parse_extra_params(args) -> dict:
    """解析 --params key=value ... 为 dict."""
    params = {}
    for item in args.params:
        if "=" in item:
            k, v = item.split("=", 1)
            # 自动类型转换
            if v.lower() == "true":
                v = True
            elif v.lower() == "false":
                v = False
            elif v.lower() == "null":
                params[k] = None
            elif v.isdigit():
                v = int(v)
            params[k] = v
    return params


def parse_body(raw: str | None) -> dict | None:
    if raw is None:
        return None
    if raw.startswith("@"):
        path = raw[1:]
        return json.loads(Path(path).read_text())
    return json.loads(raw)


def cmd_call(spec: SpecManager, client: APIClient, args, policy: AccessPolicy):
    method = args.method.upper()
    path = args.path

    op = spec.resolve(method, path)
    if op is None:
        print(f"❌ 未找到: {method} {path}", file=sys.stderr)
        print(
            f"💡 试试: openapi-cli list-paths --filter {path.split('/')[1]}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── 访问控制检查 ──
    ok, reason = policy.check(method, path, op.get("tags", []))
    if not ok:
        print(f"🚫 拒绝访问: {method} {path}", file=sys.stderr)
        print(f"   原因: {reason}", file=sys.stderr)
        print(f"💡 openapi-cli policy show 查看当前策略", file=sys.stderr)
        sys.exit(1)

    params = parse_extra_params(args)
    body = parse_body(args.data)

    data = client.call(method, path, params, body, args.paginate)

    if args.format == "json":
        OutputFormatter.json_out(data)
        return

    # data 可能被 API 包装为 {"data": [...], "totalCount": ...}
    # 也可能直接是数组
    rows = data.get("data") if isinstance(data, dict) and "data" in data else data
    if not isinstance(rows, list):
        rows = [rows] if not isinstance(rows, list) else rows
    if not isinstance(rows, list):
        OutputFormatter.json_out(rows)
        return

    total = data.get("totalCount", len(rows)) if isinstance(data, dict) else len(rows)
    print(
        f"\n📋 {op.get('summary', method + ' ' + path)} (共 {total} 条)\n",
        file=sys.stderr,
    )

    if args.cols:
        OutputFormatter.table(rows, args.cols)
    else:
        OutputFormatter.table(rows)


def cmd_list_paths(spec: SpecManager, args, policy: AccessPolicy):
    items = spec.list_paths(args.keyword)
    # 根据策略过滤
    items = policy.filter_paths(items)
    if args.format == "json":
        OutputFormatter.json_out(items)
        return
    print(f"\n📂 API Paths ({len(items)} 个)", file=sys.stderr)
    if policy.is_restrictive:
        print(f"   (已按访问策略过滤，openapi-cli policy show 查看)", file=sys.stderr)
    print(file=sys.stderr)
    OutputFormatter.table(items, ["method", "path", "summary", "tags"])


def cmd_describe(spec: SpecManager, args):
    op = spec.resolve(args.method, args.path)
    if op is None:
        print(f"❌ 未找到: {args.method.upper()} {args.path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"  {args.method.upper()} {args.path}")
    print(f"  {op.get('summary', '')}")
    print(f"  tags: {', '.join(op.get('tags', []))}")
    print(f"{'=' * 60}\n")

    resolver = ParamResolver(op)
    params = resolver.list_params()
    if params:
        print(f"📌 参数 ({len(params)} 个):")
        print(resolver.describe_params())
    else:
        print("📌 无参数")

    # 显示 body 参数（如有）
    consumes = op.get("consumes", [])
    if consumes:
        print(f"\n📦 Content-Type: {', '.join(consumes)}")
        body_params = [p for p in op.get("parameters", []) if p.get("in") == "body"]
        if body_params:
            schema_ref = body_params[0].get("schema", {}).get("$ref", "")
            if schema_ref:
                print(f"📦 Body Schema: {schema_ref}")

    # 显示响应定义
    responses = op.get("responses", {})
    if responses:
        print(f"\n📤 响应:")
        for code, resp in responses.items():
            desc = resp.get("description", "")
            schema_ref = resp.get("schema", {}).get("$ref", "")
            print(f"  {code}: {desc}" + (f" → {schema_ref}" if schema_ref else ""))


def cmd_schema(spec: SpecManager, args):
    definition = spec.get_definition(args.name)
    if definition is None:
        # 模糊搜索
        defs = spec.spec.get("definitions", {})
        matches = [k for k in defs if args.name.lower() in k.lower()]
        if matches:
            print(f"❌ 未找到 '{args.name}'，相似的有:", file=sys.stderr)
            for m in matches[:10]:
                print(f"  {m}", file=sys.stderr)
        else:
            print(f"❌ 未找到: {args.name}", file=sys.stderr)
        sys.exit(1)

    OutputFormatter.json_out(definition)


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    spec = SpecManager()
    client = APIClient(spec)
    policy = AccessPolicy()
    policy.load()

    if args.command == "refresh":
        spec.refresh()
        return

    if args.command in ("policy", "pol"):
        if args.action == "init":
            _init_policy()
        else:
            print(policy.describe(), file=sys.stderr)
            if not POLICY_FILE.exists():
                print("\n💡 策略文件不存在，当前使用默认安全策略。", file=sys.stderr)
                print(
                    "   openapi-cli policy init 生成可编辑的策略模板", file=sys.stderr
                )
        return

    if args.command == "list-paths" or args.command == "paths":
        cmd_list_paths(spec, args, policy)
        return

    if args.command in ("describe", "desc"):
        cmd_describe(spec, args)
        return

    if args.command == "schema":
        cmd_schema(spec, args)
        return

    if args.command in ("call", "GET", "POST", "PUT", "DELETE", "PATCH"):
        # 如果用别名调用，从命令名推导 method
        if args.command != "call":
            args.method = args.command
        cmd_call(spec, client, args, policy)
        return

    parser.print_help()


def _init_policy():
    """生成默认策略模板文件."""
    template = {
        "_comment": "访问控制策略文件 — 编辑后保存即可生效",
        "allow_tags": [],
        "deny_methods": ["DELETE"],
        "allow_paths": [],
        "deny_paths": [],
        "_examples": {
            "allow_tags": '["用户管理"]  只允许用户管理 tag 的接口',
            "deny_methods": '["DELETE", "PUT"]  禁止这些 HTTP 方法',
            "allow_paths": '["POST /user/list", "GET /user/detail"]  只需要这些',
            "deny_paths": '["DELETE /user/*"]  精确禁止特定路径',
        },
    }
    if POLICY_FILE.exists():
        print(f"⚠️  策略文件已存在: {POLICY_FILE}", file=sys.stderr)
        return
    POLICY_FILE.write_text(json.dumps(template, indent=2, ensure_ascii=False))
    POLICY_FILE.chmod(0o600)
    print(f"✅ 已生成策略模板: {POLICY_FILE}", file=sys.stderr)
    print(f"   编辑后生效，当前仍使用默认安全策略", file=sys.stderr)


if __name__ == "__main__":
    main()
