# Dify Speed Routing Manual

当前线上普通低落路径仍未达到 8-12 秒验收线：

- 最新 ordinary-only 复测：15.75s / 13.87s / 11.67s
- 平均：13.76s
- 报告：`test-artifacts/dify-ux-ux-focus-20260608-132712-510262.md`

## 目标

普通低风险轮只跑必要节点：

```text
turn-prep -> Risk Detection -> Risk detection parse -> 条件分支 3 -> Therapy Response -> 保存助手消息 -> 直接回复
```

只有安全风险、明确收尾、临近结束或不可继续时，才进入额外判断节点。

## 手动改图

在 Dify 网页中调整连线：

1. 断开：
   - `Risk detection parse -> Psychological Analysis`
   - `Psychological Analysis -> 条件分支 3`
   - `条件分支 3 false -> USER END INTENT DETECTION`

2. 新连：
   - `Risk detection parse -> 条件分支 3`
   - `条件分支 3 true -> Crisis Safety Response`
   - `条件分支 3 false -> 结束意图预路由`
   - `结束意图预路由 false -> Therapy Response`
   - `结束意图预路由 true -> USER END INTENT DETECTION`
   - `USER END INTENT DETECTION -> USER END INTENT DETECTION parse`
   - `USER END INTENT DETECTION parse -> Psychological Analysis`
   - `Psychological Analysis -> 条件分支 2`

保留：

- `Therapy Response -> 保存助手消息 -> 直接回复`
- `Crisis Safety Response -> 保存助手消息 (1) -> 直接回复 3`
- 结束路径的总结、画像、care plan、Finalize

## 结束意图预路由代码

输入变量：

- `current_query` = `sys.query`
- `can_continue` = `聚合查询解析.can_continue`
- `final_saved` = `聚合查询解析.final_saved`
- `session_stage` = `聚合查询解析.session_stage`
- `remaining_minutes` = `聚合查询解析.remaining_minutes`

输出变量：

- `need_end_intent_llm`: Boolean
- `route_reason`: String

```python
def main(
    current_query: str = "",
    can_continue: bool = True,
    final_saved: bool = False,
    session_stage: str = "",
    remaining_minutes: float = 50,
) -> dict:
    q = (current_query or "").strip()

    try:
        remaining = float(remaining_minutes or 0)
    except Exception:
        remaining = 0

    explicit_end_markers = [
        "今天先到这里", "先到这里", "下次再聊", "先不聊", "不聊了",
        "我要睡了", "去睡了", "睡觉了", "我要走了", "先走了",
        "差不多了", "先这样", "暂停一下", "不想继续说了"
    ]

    non_end_markers = [
        "不知道", "没啥好说", "没什么好说", "没用", "随便",
        "不想做任务", "别给方法", "别列计划", "不要给方法",
        "不要列计划", "现在还能继续", "还没说完", "继续说"
    ]

    if final_saved:
        return {"need_end_intent_llm": True, "route_reason": "final_saved"}

    if not can_continue:
        return {"need_end_intent_llm": True, "route_reason": "cannot_continue"}

    if session_stage in ["ending", "ended"] or remaining <= 2:
        return {"need_end_intent_llm": True, "route_reason": "time_or_stage"}

    if any(marker in q for marker in non_end_markers):
        return {"need_end_intent_llm": False, "route_reason": "known_non_end"}

    if any(marker in q for marker in explicit_end_markers):
        return {"need_end_intent_llm": True, "route_reason": "explicit_end_candidate"}

    return {"need_end_intent_llm": False, "route_reason": "normal_turn"}
```

## 验收命令

先只验普通速度：

```powershell
python tests\dify_ux_validation.py --scenarios ordinary --skip-backend --require-pass
```

普通速度通过后再跑全量：

```powershell
python tests\dify_ux_validation.py --require-pass
```

