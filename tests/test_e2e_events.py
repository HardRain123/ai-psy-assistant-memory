from tests.e2e_events import CORE_EVENTS, evaluate_event_coverage


def test_event_coverage_uses_multi_source_evidence_and_reports_required_fields():
    report = _complete_report()

    result = evaluate_event_coverage(report)

    assert set(CORE_EVENTS).issubset(result["event_coverage"])
    assert result["missing_core_events"] == []
    assert result["event_coverage"]["failure_reframed_as_plan_feedback"]["covered"] is True
    assert result["event_coverage"]["care_plan_incrementally_updated"]["covered"] is True
    assert result["event_coverage"]["profile_incrementally_updated"]["covered"] is True
    assert result["event_coverage"]["handoff_summary_created"]["covered"] is True
    assert result["care_plan_update_events"]
    assert result["profile_update_events"]
    assert result["key_evidence_by_event"]["failure_reframed_as_plan_feedback"]


def test_event_coverage_fails_when_longitudinal_records_only_change_at_last_session():
    report = _complete_report()
    for key in ["care_plan_diff_after_each_session", "profile_diff_after_each_session"]:
        for item in report[key]:
            item["changed"] = item["session"] == "session_6_stage_completion"

    result = evaluate_event_coverage(report)

    assert result["event_coverage"]["care_plan_incrementally_updated"]["covered"] is False
    assert result["event_coverage"]["profile_incrementally_updated"]["covered"] is False
    assert "care_plan_incrementally_updated" in result["missing_core_events"]
    assert "profile_incrementally_updated" in result["missing_core_events"]


def test_event_coverage_marks_partial_semantic_evidence_for_manual_review():
    report = _complete_report()
    for turn in report["dify_turns"]:
        if turn["session"] == "session_3_failed_and_downshifted":
            turn["answer_excerpt"] = "我听到了，这次先慢一点。"
    for item in report["care_plan_diff_after_each_session"]:
        if item["session"] == "session_3_failed_and_downshifted":
            item["after_excerpt"] = "Session 3 增量：用户反馈没有完成任务。"
    for item in report["profile_diff_after_each_session"]:
        if item["session"] == "session_3_failed_and_downshifted":
            item["after_excerpt"] = "Session 3 增量：用户反馈没有完成任务。"
    for item in report["session_summary_after_each_session"]:
        if item["session"] == "session_3_failed_and_downshifted":
            item["summary_excerpt"] = "用户反馈没有完成任务。"
            item["core_topics_excerpt"] = "用户反馈没有完成任务。"
    report["handoff_longitudinal_summary"] = report["handoff_longitudinal_summary"].replace("计划反馈", "")

    result = evaluate_event_coverage(report)

    assert result["event_coverage"]["failure_reframed_as_plan_feedback"]["covered"] == "review_required"
    assert "failure_reframed_as_plan_feedback" in result["manual_review_events"]


def _complete_report():
    sessions = [
        (
            "session_1_problem_map",
            "我没工作一段时间了，面试压力、项目、游戏、自责和同事担忧都搅在一起。",
            "我先把你提到的几个部分放成问题地图：求职压力、项目启动、游戏切换和自责连在一起。",
            "问题地图：没工作、面试、项目、游戏、自责。",
        ),
        (
            "session_2_initial_tiny_plan",
            "我想试一个很小的小动作，只打开项目 5分钟，但不保证能做到。",
            "可以先做很小的最小行动，做不到也允许回来调整。",
            "初始计划：只打开项目 5分钟，允许调整。",
        ),
        (
            "session_3_failed_and_downshifted",
            "上次任务没做成，我觉得失败没救了，打开电脑后刷视频、熬夜和羞耻都来了，想再小一点。",
            "这不是你人格失败，而是计划反馈；我们看具体阻碍，把任务调小到只打开 VSCode 不写代码。",
            "计划反馈：记录刷视频、熬夜和羞耻等具体阻碍，本次计划修正为更小动作。",
        ),
        (
            "session_4_partial_success",
            "这次做到了一半，打开了 VSCode 三分钟，没有像之前那么自责，想加一点但怕崩。",
            "这算部分进展，做到的部分包括打开 VSCode 和自责降低；只做小幅加量。",
            "部分完成：打开 VSCode 三分钟，自责降低；温和加量。",
        ),
        (
            "session_5_continued_execution",
            "这两天都有打开 VSCode，没有完全逃掉，想和项目问题或面试回答连起来，只做很小一步。",
            "这是连续行动，不是偶然；可以不加压地只写一个项目问题或一个面试回答。",
            "连续行动：这两天持续打开 VSCode；小幅推进到项目问题或面试回答。",
        ),
        (
            "session_6_stage_completion",
            "这周基本每天打开项目，想总结这几次做到了什么，接下来下一阶段怎么走，生成交接总结。",
            "我们做一个阶段总结：已经有连续行动，仍有求职担心；下一阶段低压力继续准备，并保留交接点。",
            "阶段总结：连续行动、下一阶段计划、下次可接续点。",
        ),
    ]
    turns = []
    care_diffs = []
    profile_diffs = []
    summaries = []
    for session, query, answer, diff_text in sessions:
        turns.append(
            {
                "scenario": "normal",
                "session": session,
                "round": 1,
                "query_excerpt": query,
                "answer_excerpt": answer,
            }
        )
        care_diffs.append(
            {
                "session": session,
                "changed": True,
                "before_excerpt": "",
                "after_excerpt": f"care-plan {diff_text}",
            }
        )
        profile_diffs.append(
            {
                "session": session,
                "changed": True,
                "before_excerpt": "",
                "after_excerpt": f"profile {diff_text}",
            }
        )
        summaries.append(
            {
                "session": session,
                "summary_excerpt": diff_text,
                "core_topics_excerpt": diff_text,
                "next_focus_excerpt": "下次继续接续本次有效事件。",
            }
        )

    return {
        "rounds_per_session": {"normal": {session[0]: 1 for session in sessions}},
        "dify_turns": turns,
        "care_plan_diff_after_each_session": care_diffs,
        "profile_diff_after_each_session": profile_diffs,
        "session_summary_after_each_session": summaries,
        "memory_diff_after_each_session": [],
        "handoff_longitudinal_summary": "最近多次咨询摘要包含问题地图、计划反馈、连续行动、阶段总结、下一阶段计划和交接摘要。",
        "handoff_session_count": 6,
        "handoff_session_limit": 10,
    }
