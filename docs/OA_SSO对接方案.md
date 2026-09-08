# OA SSO 对接方案

> 目标：生产期由 OA 用户部门/职位自动映射角色，替代开发期 `role` 参数。
> OA 系统：https://oa.pgecc.com/（完整 OA，有统一登录）

## 一、对接前提（需与 OA 管理员确认）

| 项 | 需确认内容 | 影响 |
|---|---|---|
| SSO 协议 | OAuth2 / CAS / SAML / 自定义 Token | 决定认证流程实现 |
| 用户信息接口 | 获取用户姓名、部门、职位、工号的 API | 决定角色映射数据源 |
| 回调地址 | OA 允许的 redirect_uri 白名单 | 需提前登记 |
| AppID/AppSecret | 应用注册凭证 | 需 OA 管理员签发 |
| 登出机制 | 是否支持单点登出 | 决定登出流程 |

## 二、认证流程设计（以 OAuth2 为例）

```
用户访问 /portal/dashboard（未登录）
    ↓
重定向到 OA 授权页：
https://oa.pgecc.com/oauth/authorize?
  client_id=<APP_ID>&
  redirect_uri=https://造价系统域名/api/auth/oauth-callback&
  response_type=code&
  state=<随机字符串>
    ↓
用户在 OA 登录并授权
    ↓
OA 回调 /api/auth/oauth-callback?code=<CODE>&state=<STATE>
    ↓
后端用 code 换取 access_token
POST https://oa.pgecc.com/oauth/token
  grant_type=authorization_code
  code=<CODE>
  redirect_uri=<回调地址>
  client_id=<APP_ID>
  client_secret=<APP_SECRET>
    ↓
用 access_token 获取用户信息
GET https://oa.pgecc.com/api/userinfo
  Authorization: Bearer <ACCESS_TOKEN>
    ↓
根据用户部门/职位映射角色（见第三节）
    ↓
写入会话（JWT Token / Session Cookie）
    ↓
重定向到用户最初访问的页面
```

## 三、角色映射规则

根据 OA 用户的**部门**和**职位**自动映射到系统三角色：

| 系统角色 | OA 部门/职位条件（示例，需确认） | 权限范围 |
|---|---|---|
| **admin** | 造价部负责人、信息部管理员、系统管理员 | 全部权限（导入/删除/设置/批次管理） |
| **estimator** | 造价部工程师、成本控制部、预算员 | 查询 + 匹配确认 + 字典维护 + 批次查看 |
| **viewer** | 其他部门（项目部、采购部、管理层等） | 只读查询（Portal 页），禁导出 |

### 映射优先级

1. **白名单优先**：配置文件中指定的工号 → admin（用于系统管理员）
2. **职位匹配**：职位名称包含"经理/负责人/主管"且部门为造价部 → admin
3. **部门匹配**：部门为造价部/成本控制部 → estimator
4. **默认**：其他 → viewer

### 映射配置示例

```yaml
# config/role_mapping.yaml
admin:
  employee_ids: ["EMP001", "EMP002"]  # 工号白名单
  departments: ["造价管理部"]
  positions: ["部门经理", "负责人", "系统管理员"]

estimator:
  departments: ["造价管理部", "成本控制部", "预算部"]
  positions: ["造价工程师", "预算员", "成本控制员"]

viewer:
  default: true  # 其他用户默认 viewer
```

## 四、后端实现结构

```
app/core/
├── security.py          # 现有：三角色定义、开发期认证
├── oauth_client.py      # 新增：OA OAuth2 客户端（授权URL、换Token、用户信息）
├── role_mapper.py       # 新增：角色映射器（部门/职位 → 系统角色）
└── session.py           # 新增：会话管理（JWT签发/验证，替代开发期Cookie）

app/api/
└── auth.py              # 新增：认证路由
    ├── GET  /api/auth/login          # 重定向到 OA 授权页
    ├── GET  /api/auth/oauth-callback # OA 回调，换Token，建会话
    ├── POST /api/auth/logout         # 登出（清除会话，可选单点登出）
    └── GET  /api/auth/me             # 当前用户信息（前端展示用）
```

### 核心代码骨架（伪代码）

```python
# app/core/oauth_client.py
class OAuthClient:
    def __init__(self, config):
        self.client_id = config.OA_CLIENT_ID
        self.client_secret = config.OA_CLIENT_SECRET
        self.authorize_url = config.OA_AUTHORIZE_URL
        self.token_url = config.OA_TOKEN_URL
        self.userinfo_url = config.OA_USERINFO_URL
        self.redirect_uri = config.OA_REDIRECT_URI

    def get_authorize_url(self, state: str) -> str:
        """生成 OA 授权页 URL。"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """用 code 换 access_token。"""
        resp = requests.post(self.token_url, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        return resp.json()

    def get_userinfo(self, access_token: str) -> dict:
        """获取用户信息（姓名、部门、职位、工号）。"""
        resp = requests.get(self.userinfo_url, headers={
            "Authorization": f"Bearer {access_token}",
        })
        return resp.json()


# app/core/role_mapper.py
class RoleMapper:
    def __init__(self, config):
        self.config = config  # 从 role_mapping.yaml 加载

    def map_role(self, userinfo: dict) -> str:
        """根据 OA 用户信息映射系统角色。"""
        employee_id = userinfo.get("employee_id", "")
        department = userinfo.get("department", "")
        position = userinfo.get("position", "")

        # 1. 工号白名单 → admin
        if employee_id in self.config["admin"]["employee_ids"]:
            return ROLE_ADMIN

        # 2. 职位+部门匹配 → admin
        if (department in self.config["admin"]["departments"] and
                any(p in position for p in self.config["admin"]["positions"])):
            return ROLE_ADMIN

        # 3. 部门匹配 → estimator
        if department in self.config["estimator"]["departments"]:
            return ROLE_ESTIMATOR

        # 4. 默认 → viewer
        return ROLE_VIEWER
```

## 五、安全考虑

| 项 | 措施 |
|---|---|
| **state 参数** | 授权请求携带随机 state，回调时校验，防 CSRF |
| **Token 存储** | access_token 不落库，仅用于换取用户信息；会话用 JWT（HttpOnly Cookie） |
| **JWT 签名** | 使用 RS256 非对称签名，密钥定期轮换 |
| **会话过期** | JWT 有效期 8 小时，支持 refresh_token 续期 |
| **角色缓存** | 用户角色登录时映射一次，写入 JWT；角色变更需重新登录 |
| **审计日志** | 每次登录/登出写 audit_log（谁、何时、IP、UA） |
| **HTTPS** | 生产环境必须 HTTPS，Cookie 设置 Secure 标志 |
| **IP 白名单** | 可选：限制仅公司内网 IP 可访问 Admin 页 |

## 六、开发期 → 生产期切换

```python
# app/core/security.py
async def get_current_user(request: Request):
    if settings.env == "development":
        # 开发期：dev_token + role 参数（现有逻辑）
        ...
    else:
        # 生产期：JWT 验证（OA SSO 登录后签发）
        token = request.cookies.get("zj_session")
        if not token:
            raise HTTPException(401, "未登录")
        try:
            payload = jwt.decode(token, JWT_PUBLIC_KEY, algorithms=["RS256"])
            return {
                "username": payload["sub"],
                "role": payload["role"],
                "employee_id": payload.get("employee_id"),
            }
        except JWTError:
            raise HTTPException(401, "会话已过期，请重新登录")
```

## 七、实施步骤

| 阶段 | 内容 | 预计工时 |
|---|---|---|
| **1. 调研确认** | 与 OA 管理员确认 SSO 协议、接口、凭证 | 1-2 天 |
| **2. 配置准备** | 注册应用、获取 AppID/AppSecret、登记回调地址 | 0.5 天 |
| **3. 核心开发** | oauth_client.py + role_mapper.py + auth.py 路由 | 2-3 天 |
| **4. 角色映射配置** | 整理部门/职位清单，编写 role_mapping.yaml | 1 天 |
| **5. 联调测试** | 与 OA 系统联调，测试登录/登出/角色映射 | 2 天 |
| **6. 安全审计** | 渗透测试、代码审查、安全加固 | 1 天 |
| **7. 上线切换** | 生产环境部署，切换到 OA SSO | 0.5 天 |

**总计：约 8-10 天**

## 八、备选方案（若 OA 不支持标准 SSO）

| 方案 | 适用场景 | 优缺点 |
|---|---|---|
| **反向代理认证** | OA 支持反向代理注入用户信息（如 nginx auth_request） | 优点：无需改 OA；缺点：依赖网络架构 |
| **LDAP/AD 对接** | OA 用户存储在 LDAP/AD | 优点：标准协议；缺点：只能认证，角色映射需额外数据源 |
| **数据库直连** | OA 数据库可只读访问 | 优点：简单直接；缺点：安全风险高，需 DBA 配合 |
| **自定义 Token** | OA 提供自定义 Token 生成接口 | 优点：灵活；缺点：需 OA 开发配合 |

---

**待确认事项**：
1. OA 系统支持哪种 SSO 协议？
2. 是否有现成的用户信息 API？
3. 角色映射规则（部门/职位清单）需造价部负责人确认。
