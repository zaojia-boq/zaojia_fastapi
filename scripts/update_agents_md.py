"""更新AGENTS.md：添加大数据量页面性能优化规则"""

file_path = r'E:\DEEPSEEK学习\zaojia_fastapi\AGENTS.md'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 在"注意事项"部分的Git操作铁律之后添加性能优化铁律
old_section = """- **破坏性 git 操作前先建备份分支**：`git branch backup-<date>` 成本极低，必做。

## 测试命令约定"""

new_section = """- **破坏性 git 操作前先建备份分支**：`git branch backup-<date>` 成本极低，必做。

### 大数据量页面性能铁律（2026-09-14 字典页面事故教训，永久生效）

> 背景：material_dict 表 156,733 条数据（5 级结构），原页面全量加载 + 递归展开，导致页面加载超时（>60 秒）甚至服务无响应。以下铁律对本仓库所有涉及大数据量（>1000 条）的页面永久适用。

- **禁止全量加载树形数据**：超过 1000 条的树形结构必须懒加载（初始只加载前两级，子节点点击展开时按需请求）。违反本条视为流程违规，交付无效。
- **禁止后端递归展开**：后端查询只返回当前层级，不得在 Python 侧递归遍历所有子节点（会导致 O(n) 数据库查询 + 内存溢出）。
- **大节点必须分页**：单节点子节点超过 100 条必须分页（默认 page_size=100，最大 500），前端显示"加载更多"按钮，不得一次性渲染全部子节点。
- **前端必须缓存**：已加载的子节点必须缓存到内存（JS 对象/Map），展开/收起不重复请求网络；缓存 key=nodeId，value={page, data, loadedAll, total}。
- **复合索引必须建**：树形表必须建 (parent_id, name) 复合索引，加速子节点排序查询；仅有 parent_id 单字段索引不够。
- **搜索必须防抖**：树内/列表搜索框输入事件至少 200ms 防抖，避免每次按键都触发重渲染/请求。
- **性能验收标准**：大数据量页面（>1000 条）初始加载必须 < 500ms，子节点按需加载必须 < 200ms；超过此阈值视为性能不达标，不得交付。

**标准实现模式（强制沿用，详见 `项目总控.md` §10.9）**：
1. 后端：`get_xxx_tree()` 只加载前两级；新增 `/api/xxx/children?parent_id=xxx&page=n&page_size=n` API
2. 前端：`bindXxxTree()` 维护 cache 对象；点击展开检查 `data-loaded`；"加载更多"按钮 `data-load-more` 属性
3. 数据库：`CREATE INDEX ix_xxx_parent_name ON xxx (parent_id, name)`

## 测试命令约定"""

content = content.replace(old_section, new_section)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('AGENTS.md 更新完成！')
print(f'文件大小: {len(content)} 字符')
