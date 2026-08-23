## 一、总体原则

1. **工具优先于文档**：所有格式类规范必须通过 ESLint / Prettier / Ruff 自动执行，人工检查仅针对业务逻辑。
2. **类型优先**：TypeScript 和 Python 类型注解是强制要求，禁止使用 `any`（TS）和无注解的函数（Python）。
3. **安全红线**：密码、密钥、Token 一律不得硬编码，必须通过环境变量注入。

------

## 二、前端规范（Vue 3.5 + TypeScript 7 + Vite 8）

### 2.1 编码风格与格式化

| 配置项 | 规范要求   | 工具配置                         |
| :----- | :--------- | :------------------------------- |
| 缩进   | 2 个空格   | Prettier: `tabWidth: 2`          |
| 引号   | 单引号     | Prettier: `singleQuote: true`    |
| 分号   | 必须使用   | Prettier: `semi: true`           |
| 行宽   | 100 字符   | Prettier: `printWidth: 100`      |
| 尾逗号 | 多行时必须 | Prettier: `trailingComma: 'all'` |

**ESLint 配置要点**-：

javascript



复制



下载

```
// eslint.config.js
import vueTs from '@vue/eslint-config-typescript'
export default [
  ...vueTs(),
  // 必须配合 eslint-config-prettier 放在 extends 末尾，避免规则冲突
]
```



### 2.2 组件规范

**文件组织**：

text



复制



下载

```
src/
├── components/
│   ├── ui/              # 通用 UI 组件（BaseButton.vue）
│   └── features/        # 业务组件（UserCard/UserCard.vue）
├── composables/         # 组合式函数（useAuth.ts）
├── stores/              # Pinia 存储（userStore.ts）
├── views/               # 页面级组件（路由视图）
└── types/               # 全局类型定义
```



**SFC 块顺序**：

vue



复制



下载

```
<script setup lang="ts">  // 1. 脚本（必须使用 <script setup>）
</script>
<template>                // 2. 模板
</template>
<style scoped>            // 3. 样式（必须 scoped）
</style>
```



**组件命名**：

- 文件名：`PascalCase`（`UserProfile.vue`）
- 模板中使用：`kebab-case`（`<user-profile />`）
- 多单词命名，避免与 HTML 元素冲突

### 2.3 Props、Emits 与类型

**Props 定义**（必须使用类型声明 + `withDefaults`）：

typescript



复制



下载

```
interface Props {
  userId: string
  variant?: 'compact' | 'expanded'
  showActions?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  variant: 'compact',
  showActions: true,
})
```



**Emits 定义**（必须使用类型签名）：

typescript



复制



下载

```
const emit = defineEmits<{
  'update:modelValue': [value: string]
  delete: [id: string]
  submit: [data: FormData]
}>()
```



**v-model**（Vue 3.4+ 优先使用 `defineModel`）：

typescript



复制



下载

```
const model = defineModel<string>({ required: true })
```



### 2.4 组合式函数（Composables）

**命名规范**：必须以 `use` 开头：

- ✅ `useLocalStorage(key)`、`useAsyncData(url)`
- ❌ `getLocalStorage()`（这是普通函数，不是组合式函数）

**提取时机**：

- 逻辑在 2+ 个组件中复用
- 有状态（维护内部状态）
- 有副作用（订阅、定时器、需要清理）

**示例**：

typescript



复制



下载

```
export function useFormValidation<T>(initialData: T) {
  const data = ref(initialData)
  const errors = reactive<Record<string, string>>({})
  const reset = () => { /* ... */ }
  onUnmounted(() => { /* cleanup */ })
  return { data, errors, reset }
}
```



### 2.5 Pinia 状态管理

**必须使用 Setup Store 语法**（而非 Options Store），以获得完整的 TypeScript 类型推断-：

typescript



复制



下载

```
// stores/userStore.ts
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', () => {
  const currentUser = ref<User | null>(null)
  const isAuthenticated = computed(() => currentUser.value !== null)
  
  async function login(credentials: Credentials) {
    // ...
  }
  
  return { currentUser, isAuthenticated, login }
})
```



**TypeScript 配置**：确保 `tsconfig.json` 中 `strict: true`（或至少 `noImplicitThis: true`），Pinia 会自动推断类型-。

### 2.6 Vue Router 路由

**路由配置类型**：使用 `RouteRecordRaw`-：

typescript



复制



下载

```
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/user/:id', component: () => import('@/views/UserView.vue') }
]
```



**Meta 字段类型扩展**-：

typescript



复制



下载

```
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    title?: string
  }
}
```



**推荐插件**：`vite-plugin-vue-typed-router` 可自动生成强类型路由映射-。

### 2.7 ECharts 使用规范

**核心原则**-：

1. **实例存储**：使用 `shallowRef` 或普通变量，**不要**用 `ref`/`reactive` 包装 ECharts 实例（避免响应式系统追踪导致性能问题）
2. **按需引入**：避免全量引入 ECharts-
3. **内存管理**：必须在 `onBeforeUnmount` 中调用 `dispose()` 销毁实例-
4. **窗口自适应**：`resize` 事件必须使用防抖/节流-
5. **数据更新**：使用 `setOption` 的增量更新机制，仅传递变化部分-

**示例**：

typescript



复制



下载

```
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { markRaw, shallowRef, onBeforeUnmount } from 'vue'

const chartInstance = shallowRef<echarts.ECharts | null>(null)

onMounted(() => {
  chartInstance.value = markRaw(echarts.init(containerRef.value))
})

onBeforeUnmount(() => {
  chartInstance.value?.dispose()
})
```



### 2.8 Vue Flow 使用规范

**版本兼容性**：Vue 3.3+、TypeScript 5.0+-

**节点与边**：

- 每个节点和边必须有唯一 ID-
- 节点必须包含 `position: { x, y }`
- 边必须包含 `source` 和 `target` 节点 ID-

**自定义节点**：插槽内容必须是纯 HTML，不能使用 `<component :is="...">`，否则 Vue Flow 的内部 diff 会失效-

------

## 三、后端规范（Python 3.10 + FastAPI）

### 3.1 编码风格与格式化

| 配置项   | 规范要求                         | 工具配置          |
| :------- | :------------------------------- | :---------------- |
| 缩进     | 4 个空格                         | Ruff              |
| 行宽     | 88 字符                          | Ruff (Black 风格) |
| 引号     | 双引号                           | Ruff              |
| 类型注解 | 所有函数必须标注参数和返回值类型 | mypy `--strict`   |

**工具链**：

- **Lint**：`ruff check .`
- **格式化**：`ruff format .`
- **类型检查**：`mypy . --strict`

**禁止项**-[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)：

- ❌ 禁止使用 `Any` 类型（除非有 justification 注释）
- ❌ 禁止在生产代码中使用 `print()`（使用 `loguru` 或 `logging`）
- ❌ 禁止硬编码密钥/密码/Token

### 3.2 项目结构（按领域划分）

推荐按 **领域（Domain）** 而非文件类型组织代码：

text



复制



下载

```
fastapi-project/
├── alembic/                    # 数据库迁移
├── src/
│   ├── auth/                   # 认证领域
│   │   ├── router.py           # 路由（端点定义）
│   │   ├── schemas.py          # Pydantic 模型
│   │   ├── models.py           # SQLAlchemy 模型
│   │   ├── service.py          # 业务逻辑
│   │   ├── dependencies.py     # 依赖注入
│   │   ├── exceptions.py       # 领域异常
│   │   └── constants.py        # 常量
│   ├── posts/                  # 帖子领域（同样结构）
│   ├── config.py               # 全局配置
│   ├── database.py             # 数据库连接
│   └── main.py                 # FastAPI 应用入口
├── tests/                      # 测试（镜像 src 结构）
├── .env
└── pyproject.toml              # Ruff/mypy 配置
```



**分层原则**[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)：

- **Router** → 只负责路由和参数解析，调用 Service
- **Service** → 业务逻辑，调用 Repository/Model
- **禁止**：Router 中直接操作数据库
- **禁止**：Service 中引入 HTTP 类型（如 `Request`）

### 3.3 FastAPI 路由规范

**必须使用 `Annotated` 声明依赖注入**-：

python



复制



下载

```
from typing import Annotated
from fastapi import Depends, FastAPI

app = FastAPI()

def get_current_user(token: str) -> User:
    # ...

@app.get("/profile")
async def get_profile(
    current_user: Annotated[User, Depends(get_current_user)]
) -> UserResponse:
    # ...
```



**异步路由**：

- 只有调用 `await` 异步代码时才使用 `async def`-
- 所有异步路由函数必须显式标注返回类型-
- 所有异步函数必须正确处理异常[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)

**统一响应格式**-：

python



复制



下载

```
class APIResponse(BaseModel):
    code: int = 0
    msg: str = "success"
    data: Any = None
```



### 3.4 Pydantic 模型规范（v2）

**版本要求**：使用 Pydantic v2 API，禁止使用 v1 的 `@validator` 装饰器-[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)

**模型定义**[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)：

python



复制



下载

```
from pydantic import BaseModel, ConfigDict, Field, field_validator

class UserCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # 支持 ORM 对象转换
    
    email: str = Field(..., min_length=1, max_length=100)
    name: str
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower()

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
```



**序列化**：使用 `model_dump()` 而非 `dict()`（Pydantic v2）-

### 3.5 SQLAlchemy 2.0 模型规范

**异步优先**：必须使用 `AsyncSession`，禁止使用同步 `Session`-[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)

**模型定义**（使用 `Mapped` 注解）-：

python



复制



下载

```
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
```



**查询规范**[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)：

- 使用 `select()` 风格（非旧的 `query()` 风格）
- 使用 `selectinload()` 进行预加载
- 始终将 `AsyncSession` 作为上下文管理器使用

python



复制



下载

```
async def get_user_posts(db: AsyncSession, user_id: int) -> list[Post]:
    result = await db.execute(
        select(Post)
        .where(Post.user_id == user_id)
        .options(selectinload(Post.author))
        .order_by(Post.created_at.desc())
    )
    return list(result.scalars().all())
```



### 3.6 Alembic 迁移规范

**命名约定**-：

python



复制



下载

```
# 在 models.py 的 Base 中配置
metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
})
```



**迁移工作流**-：

1. 修改模型后执行 `alembic revision --autogenerate -m "描述"`
2. **必须检查**自动生成的迁移脚本（复杂变更可能不准确）
3. 向现有表添加非空列时，必须提供默认值或允许为空
4. 迁移脚本必须可回滚

### 3.7 HTTPX 使用规范

**客户端复用**：使用连接池，复用同一个客户端实例-

**超时设置**-：

python



复制



下载

```
import httpx

# 默认超时 5 秒，建议显式设置
client = httpx.AsyncClient(timeout=10.0)
```



**异步优先**：在 FastAPI 中优先使用 `AsyncClient`-

**错误处理**：必须捕获 `httpx.HTTPError` 并妥善处理

### 3.8 安全与加密规范

**密码哈希**（argon2-cffi）-：

python



复制



下载

```
from argon2 import PasswordHasher

ph = PasswordHasher()  # 默认使用 Argon2id，自动生成随机盐
hash = ph.hash("password")
ph.verify(hash, "password")  # 验证
```



**加密**（cryptography）-：

- ❌ 禁止自己发明加密方案
- ✅ 必须使用认证加密模式：AES-GCM 或 ChaCha20-Poly1305
- ❌ 禁止使用未认证模式：AES-CBC、AES-CTR（单独使用）
- 使用 `cryptography` 库的高层 API（如 `Fernet`）可避免常见错误-

**密钥管理**：

- 密钥、密码、Token 一律通过环境变量注入
- 日志中不得打印密码或 Token[-50](https://dev.to/myougatheaxo/pythonfastapi-development-with-claude-code-claudemd-setup-hooks-and-best-practices-1f11#1)

### 3.9 图像处理规范（Pillow + NumPy + OpenCV）

**Pillow**-：

python



复制



下载

```
from PIL import Image  # ✅ 正确
# import Image  # ❌ 错误（Pillow >= 1.0 不支持）
```



- 批量处理时及时释放资源：`del img` + `gc.collect()`-
- 保存 JPEG 前必须 `convert('RGB')` 去除 Alpha 通道-

**OpenCV + NumPy**-：

- OpenCV 读取图像默认是 **BGR** 通道顺序（不是 RGB）
- 使用 `cv2.cvtColor(img, cv2.COLOR_BGR2RGB)` 转换
- 大数据类型转换：先转 `float32` 完成计算，最后统一转回-
- 对 OpenCV 图像优先使用 `cv2` 函数，而非 NumPy 手动操作-

**PaddleOCR**-：

- 代码遵循 PEP8 规范
- 推荐使用 Python 3.7-3.10，通过 conda 创建独立虚拟环境-
- 生产环境建议使用包含 PP-OCRv3 模型的完整版-

------

## 四、自动化工具链（强制执行层）

### 4.1 Git Hooks（推荐 husky + lint-staged）

| 阶段         | 检查内容               | 不通过则 |
| :----------- | :--------------------- | :------- |
| `pre-commit` | 格式化 + Lint 自动修复 | 阻止提交 |
| `pre-push`   | 完整 Lint + TypeCheck  | 阻止推送 |

### 4.2 CI/CD 检查项（PR 合入前必须全部通过）

| 前端                     | 后端                                 |
| :----------------------- | :----------------------------------- |
| `pnpm lint`              | `ruff check .`                       |
| `pnpm type-check`        | `mypy . --strict`                    |
| `pnpm test`              | `pytest`（含覆盖率）                 |
| 构建成功（`pnpm build`） | `alembic check`（检测 Schema 漂移）- |

### 4.3 配置文件清单

| 文件                                | 用途                              |
| :---------------------------------- | :-------------------------------- |
| `.eslintrc.js` / `eslint.config.js` | Vue 3 + TS Lint                   |
| `.prettierrc`                       | 前端格式化                        |
| `tsconfig.json`                     | TypeScript（必须 `strict: true`） |
| `pyproject.toml`                    | Ruff + mypy 配置                  |
| `.editorconfig`                     | 跨编辑器基础格式统一              |
| `.vscode/settings.json`             | 保存时自动格式化                  |

------

## 五、例外机制

任何规范都存在特殊情况。当需要违反规范时：

1. 在代码中添加 `// eslint-disable-next-line` 或 `# noqa` 注释
2. **必须写明原因**（Why），而非仅仅禁用检查
3. 需要团队 Lead 在 PR 中 Approve