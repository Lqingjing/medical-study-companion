# 架构说明（V0.1）

本文件说明各模块职责、数据形状与关键接口，供阅读代码时对照。公开版不含真实数据，示例字段仅描述结构。

## 1. 总体结构

```
┌────────────────┐     ┌──────────────────┐     ┌────────────────┐
│ 内容源 JSON     │     │ 题库原始文件      │     │ 讲义 PDF / 导图 │
│ content/*.json │     │ (本地，未公开)    │     │ (本地，未公开)  │
└───────┬────────┘     └────────┬─────────┘     └───────┬────────┘
        │                       │                       │
        └───────────┬───────────┘                       │
                    ▼                                   │
            compile_units.py                            │
                    │  生成 {unit}.json                  │
                    ▼                                   │
            ┌───────────────────┐                       │
            │  server.py         │◄─────────────────────┘
            │  本机 HTTP 服务    │  按页读取 PDF
            └─────────┬─────────┘
                      │ JSON API / PDF 流
                      ▼
            ┌───────────────────┐
            │ app.js + reader.js │
            │ 浏览器单页界面      │
            └───────────────────┘
```

- 单机、单进程、无数据库：每章一个 JSON 会话文件。
- 无前端构建：直接加载源码。
- 服务默认只监听 `127.0.0.1`。

## 2. 模块职责

| 模块 | 职责 | 关键点 |
|---|---|---|
| `server.py` | 章节注册、请求路由、会话读写、PDF 流、追问转发 | 通过向上查找项目根定位资料目录；拒绝越界路径 |
| `app.js` | 前端状态机：章节/小节导航、题库筛选、题卡、反馈、位置保存 | 数据驱动，不硬编码疾病名与题量 |
| `original-reader.js` | PDF.js 封装：页定位、书页换算、选字、勾画 | `unit:sourceId` 作为缓存键 |
| `compile_units.py` | 把内容源与题库合并为 `{unit}.json` | 每章一个 `compile_*` 函数 + 分类函数 |
| `build_unit.py` | 编译 + 门禁的一站式入口 | 失败即非零退出 |
| `verify_unit.py` | 章节门禁：HTTP、PDF 流、路由、入口文件 | 使用临时会话，不动正式数据 |
| `test_server.py` | 服务端回归测试 | 覆盖章节隔离、作答、旧题号兼容 |
| `agent.py` | 本机模型客户端适配 | 不保存、不转发任何凭据 |
| `launch.py` | 选端口、起服务、打开浏览器 | 入口脚本调用它 |

## 3. 章节数据形状（`{unit}.json`）

```jsonc
{
  "id": "asthma-trial-20261114",     // 章节标识
  "title": "支气管哮喘",
  "stage": "…",                       // 展示用阶段描述
  "version": "2026-11-17.1",
  "sources": {                        // 讲义/导图/题库来源（相对项目根）
    "tt-handout": { "path": "…/handout.pdf", "label": "…", "kind": "handout" }
  },
  "sections": [                       // 小节树
    { "id": "symptoms", "title": "临床表现", "type": "reading" }
  ],
  "questions": [
    {
      "id": "tt-01",
      "qid": "TT-ASTHMA-01",
      "tier": "tier1",                // tier1 课后 / tier2 执医 / tier3 考研
      "tierLabel": "🥇 课后题",
      "exam": "第 1 题",
      "section": "treatment",
      "stem": "…",
      "options": [{ "key": "A", "text": "…" }],
      "answer": "C",
      "explanation": "…",
      "feedback": {
        "derivation": "…",
        "note": "…",
        "targetSection": "treatment", // 反馈可跳回的小节
        "targetPage": 4               // 对应讲义页
      }
    }
  ],
  "overview": { },                    // 章节概览
  "resourceShelf": [ ],               // 资源架
  "metadata": { }
}
```

设计取舍：

- **题目带 `section` 与 `feedback.targetSection`**：同一道题可以既属于练习小节，又能定位回讲义小节。
- **`tier` 稳定**：前端按层筛选，编译期不重排，保证计数与历史记录可对账。
- **`sources` 只存相对路径**：换机器只需保持项目根下的资料布局。

## 4. 会话数据形状（`data/session.json`）

```jsonc
{
  "version": 1,
  "unit": "asthma-trial-20261114",
  "unitVersion": "2026-11-14.1",
  "section": "symptoms",              // 最后阅读小节
  "threadId": "…",                    // 模型会话标识（不公开）
  "messages": [                       // 追问记录
    { "id": "…", "role": "user", "text": "…", "section": "practice",
      "selection": "…", "question": null, "origin": null,
      "time": "2026-11-15T23:52:24+08:00", "requestId": "…" }
  ]
}
```

作答、勾画、位置分别由服务端写入同一章的会话文件，避免多份真相。

**历史作答兼容**：旧版本使用 `tt-pte-1` 这类题号，新版本为 `tt-pte-01`。服务端在读取 PTE 历史作答时做只读题号映射：旧键、旧理由、旧反馈保留原样，新作答写入当前题号。

## 5. 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/units` | 已注册章节列表 |
| GET | `/api/unit?unit=` | 章节数据（小节、题目、来源） |
| GET | `/api/state?unit=` | 当前小节、作答统计、位置 |
| POST | `/api/attempt` | 提交作答（选择 + 理由） |
| POST | `/api/annotation` | 保存勾画 |
| GET | `/api/annotation-status` | 查询勾画状态 |
| POST | `/api/recall` | 记录主动回忆结果 |
| POST | `/api/position` | 保存阅读位置 |
| POST | `/api/ask` | 带上下文追问 |
| POST | `/api/stop` | 停止本机服务 |
| GET | `/pdf/...` | 按页返回讲义 PDF 流 |

写接口只接受已注册章节；未知章节直接拒绝，避免任意读写。

## 6. 构建与门禁

```bash
# 编译 + 门禁
python build_unit.py --unit asthma
python build_unit.py --unit pte

# 或分步
python compile_units.py
python verify_unit.py asthma
python -m unittest -v test_server.py
```

门禁内容：

1. 章节已注册且可返回数据；
2. 讲义 PDF 可按页读取；
3. 未知章节被拒绝；
4. 入口文件（快捷方式）存在且参数正确；
5. 服务端行为回归（作答、隔离、旧题号兼容、只读文件不被改写）。

门禁使用临时会话，不触碰正式 `data/`。

## 7. 依赖

| 依赖 | 用途 | 公开包 |
|---|---|---|
| Python 3.12 | 服务与编译脚本 | 需要 |
| PyMuPDF | 读取讲义 PDF 页 | 需要（本地安装） |
| PDF.js | 浏览器端 PDF 渲染 | 不包含，需自行获取（Apache-2.0） |
| 无 | 数据库、Web 框架、前端构建 | — |

## 8. 扩展一章需要改什么

1. 新增 `content/{disease}_content.json`（小节、概览、来源、快捷问题）；
2. 在 `compile_units.py` 增加 `compile_{disease}()` 与分类函数；
3. 在 `UNIT_REGISTRY` 注册一行；
4. 可选：新增入口快捷方式（门禁会检查）。

前端不需要按疾病加分支，也不需要改题量常量。

## 9. 隐私与边界

- 服务只监听本机回环地址；
- 会话文件、讲义、题库都在本机，不入仓库；
- 追问会把当前小节、选区或题目上下文发送给本机已登录的模型客户端，是否启用由本机配置决定；
- 公开仓库不含上述任何数据。
