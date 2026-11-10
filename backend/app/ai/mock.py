"""Deterministic MockProvider answers (Plan §5.4 provider adapter; §7.3 CI runs).

Each answer is schema-valid, in the requested language, cites the first retrieved chunk label
when retrieval was sufficient, and passes the output rules. The text is generic on purpose.
`hints` come from the AI service and are never sent to a real provider.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.provider import LLMRequest

# Mock-only trigger: a student message containing this makes the mock coach produce a sentence
# that breaks the output rules, so tests can show it never reaches the browser.
MOCK_RULE_VIOLATION = "[[mock:rule-violation]]"


def _t(lang: str, zh: str, en: str) -> str:
    return zh if lang == "zh-CN" else en


def _base(request: LLMRequest) -> dict[str, Any]:
    labels = request.hints.get("labels") or []
    grounded = bool(labels) and bool(request.hints.get("sufficient"))
    return {
        "source_chunk_ids": labels[:1] if grounded else [],
        "grounding": "manual"
        if grounded
        else ("general" if request.hints.get("retrieval") else "none"),
        "confidence": "medium",
    }


def _mcq(lang: str, skill: str, n: int) -> dict[str, Any]:
    return {
        "scenario_text": _t(
            lang,
            f"小林在学校遇到一件小麻烦，想试试“{skill}”。（第{n}题）",
            f"Alex hits a small problem at school and wants to try {skill}. (Question {n})",
        ),
        "question_text": _t(
            lang, "哪一种做法最符合这个技能？", "Which choice fits this skill best?"
        ),
        "options": [
            _t(
                lang,
                f"先停一下，按{skill}的步骤慢慢来（{n}）",
                f"Pause and follow the {skill} steps slowly ({n})",
            ),
            _t(lang, f"马上做决定，不去想（{n}）", f"Decide at once without thinking ({n})"),
            _t(lang, f"假装什么都没发生（{n}）", f"Pretend nothing happened ({n})"),
            _t(lang, f"把问题都怪到别人身上（{n}）", f"Put all the blame on someone else ({n})"),
        ],
        "correct_option": 0,
        "explanation": _t(
            lang,
            "第一个选项在练习这个技能；其他选项是在回避或指责。",
            "The first choice practises the skill; the others avoid the moment or blame someone.",
        ),
    }


def default_response(request: LLMRequest) -> str:
    lang = str(request.hints.get("language", "zh-CN"))
    skill = str(request.hints.get("skill_name") or _t(lang, "这个技能", "this skill"))
    module = str(request.hints.get("module_name") or _t(lang, "这个模块", "this module"))
    base = _base(request)
    f = request.function
    out: dict[str, Any]
    if f == "personal_inquiry":
        out = {
            "greeting": _t(
                lang,
                "谢谢你告诉我现在的心情。不管心情怎样，都可以慢慢来。",
                "Thanks for sharing how you feel right now. Whatever the mood, we can take it slowly.",
            ),
            "question": _t(
                lang,
                "如果你愿意，可以说说最近有什么让你印象深刻的事吗？不想说也完全没关系。",
                "If you like, is there something from the last few days that stood out to you? It is fine to skip this.",
            ),
            "inquiry_focus": _t(lang, "近期状态", "recent days"),
        }
    elif f == "select_skill":
        allowed = request.hints.get("allowed_skills") or [["mf.what_skills", "mindfulness"]]
        recent = set(request.hints.get("recent_skills") or [])
        pick = next((s for s in allowed if s[0] not in recent), allowed[0])
        alts = [s[0] for s in allowed if s[0] != pick[0]][:2]
        out = {
            "selected_module": pick[1],
            "selected_skill": pick[0],
            "reason": _t(
                lang,
                "这个技能适合先从小步练习开始。",
                "This skill is a good small first step to practise.",
            ),
            "skill_difficulty": "beginner",
            "alternative_skills": alts,
            "is_repeat": False,
            "repeat_justification": "",
        }
    elif f == "teaching_plan":
        out = {
            "module": module,
            "skill": skill,
            "plan_steps": [
                {
                    "step_number": 1,
                    "title": _t(lang, "从一个小场景开始", "Start with a small scene"),
                    "content": _t(
                        lang,
                        f"用一个校园里的小例子引出{skill}。",
                        f"Use a small school example to introduce {skill}.",
                    ),
                    "estimated_minutes": 3,
                },
                {
                    "step_number": 2,
                    "title": _t(lang, "一起练一练", "Practise together"),
                    "content": _t(
                        lang,
                        "一步一步练习，并说说注意到了什么。",
                        "Practise step by step and notice what happens.",
                    ),
                    "estimated_minutes": 8,
                },
                {
                    "step_number": 3,
                    "title": _t(lang, "带回日常", "Take it into the week"),
                    "content": _t(
                        lang, "想一个这周可以用到的时刻。", "Pick one moment this week to try it."
                    ),
                    "estimated_minutes": 4,
                },
            ],
        }
    elif f in ("teaching_opening", "teaching_turn"):
        content = _t(
            lang,
            f"我们来练习{skill}。先慢慢做一次，注意自己此刻的感受。",
            f"Let's practise {skill}. Try it once slowly and notice how you feel right now.",
        )
        question = _t(lang, "你注意到了什么？", "What did you notice?")
        message_type = "practice"
        if f == "teaching_turn" and request.hints.get("closing"):
            message_type = "summary"
            content = _t(
                lang,
                f"今天我们一起练习了{skill}，你一步一步地完成了练习。",
                f"Today we practised {skill} together, one step at a time.",
            )
            question = ""
        if f == "teaching_turn" and any(
            MOCK_RULE_VIOLATION in m.get("content", "") for m in request.messages
        ):
            # E2E/test trigger (mock only): a sentence the output rules must reject.
            content = _t(lang, "你就是太敏感了。", "You are just too sensitive.") + " " + content
        if f == "teaching_turn" and request.hints.get("streamed"):
            meta = {
                **base,
                "message_type": message_type,
                "question": question,
                "risk_level": "none",
                "should_stop": False,
                "risk_reasoning": "",
            }
            return (
                content
                + "\n\n"
                + question
                + "\n<!--META:"
                + json.dumps(meta, ensure_ascii=False)
                + "-->"
            )
        out = {"message_type": message_type, "content": content, "question": question}
    elif f == "teaching_summary":
        out = {
            "skill_covered": skill,
            "key_points": [
                _t(lang, "先停下来再行动", "Pause before acting"),
                _t(lang, "注意此刻的感受", "Notice what you feel now"),
                _t(lang, "选一个小步骤去试", "Pick one small step to try"),
            ],
            "understanding": "fair",
            "recommendations": [
                _t(lang, "这周找一个时刻再练一次", "Practise once more this week"),
                _t(
                    lang,
                    "下次可以和治疗师聊聊练习感受",
                    "Talk about the practice with your therapist next time",
                ),
            ],
            "summary_text": _t(
                lang,
                f"这次我们练习了{skill}，你认真参与了练习。",
                f"Today we practised {skill}, and you took part in the practice.",
            ),
        }
    elif f == "generate_skill_test":
        out = {
            "questions": [_mcq(lang, skill, n) for n in range(1, 6)],
            "test_difficulty": "beginner",
        }
    elif f == "explain_skill":
        out = {
            "title": skill,
            "summary": _t(
                lang,
                f"{skill}是一个可以在压力时刻帮助你先停下来、再选择怎么回应的技能。",
                f"{skill} helps you pause in a stressful moment and then choose how to respond.",
            ),
            "key_points": [
                _t(lang, "先注意自己的感受", "Notice your own feelings first"),
                _t(lang, "放慢一点再回应", "Slow down before responding"),
                _t(lang, "选择一个小而具体的行动", "Choose one small, concrete action"),
            ],
            "everyday_example": _t(
                lang,
                "比如排队很久时感到烦躁，先深呼吸一次，再决定怎么做。",
                "For example, when a long queue feels irritating, take one breath and then decide what to do.",
            ),
            "check_question": _t(
                lang, "你这周可能在什么时候用到它？", "When might you use this skill this week?"
            ),
        }
    elif f == "generate_practice_items":
        out = {
            "items": [
                {
                    "scenario": _t(
                        lang,
                        "在超市里，结账的队伍突然变得很长。",
                        "At the supermarket, the checkout queue suddenly gets long.",
                    ),
                    "prompt": _t(
                        lang, "哪种回应最符合这个技能？", "Which response fits the skill best?"
                    ),
                    "answer_mode": "choice",
                    "options": [
                        {
                            "text": _t(
                                lang,
                                "先注意自己的烦躁，再慢慢回应",
                                "Notice the irritation, then respond slowly",
                            ),
                            "rubric_tag": "skill_used",
                        },
                        {"text": _t(lang, "大声抱怨", "Complain loudly"), "rubric_tag": "reactive"},
                        {
                            "text": _t(lang, "转身离开，什么都不想", "Walk off without thinking"),
                            "rubric_tag": "avoidant",
                        },
                    ],
                },
                {
                    "scenario": _t(
                        lang,
                        "同事临时改了会议时间。",
                        "A colleague moves a meeting at short notice.",
                    ),
                    "prompt": _t(
                        lang,
                        "用一两句话写下你会怎样运用这个技能。",
                        "In a sentence or two, how would you use the skill here?",
                    ),
                    "answer_mode": "short_text",
                    "options": [],
                },
            ]
        }
    elif f == "evaluate_practice_answer":
        out = {
            "category": str(request.hints.get("rubric_tag") or "partly_used"),
            "what_worked": _t(
                lang, "你注意到了当时的感受。", "You noticed what you felt in the moment."
            ),
            "why": _t(
                lang,
                "先注意感受，能给自己留出选择怎么回应的空间。",
                "Noticing the feeling first gives you room to choose how to respond.",
            ),
            "try_next": _t(
                lang, "下次可以再加一个具体的小行动。", "Next time, add one small concrete action."
            ),
            "allow_retry": True,
        }
    elif f == "generate_quiz":
        out = {
            "questions": [
                {
                    "stem": _t(
                        lang,
                        f"关于{skill}，哪一句最准确？（第{n}题）",
                        f"Which statement about {skill} is most accurate? (Question {n})",
                    ),
                    "options": [
                        _t(
                            lang,
                            f"它帮助你先停下来再选择（{n}）",
                            f"It helps you pause and then choose ({n})",
                        ),
                        _t(
                            lang,
                            f"它要求你马上解决所有问题（{n}）",
                            f"It means solving everything at once ({n})",
                        ),
                        _t(lang, f"它只适合专业人员（{n}）", f"It is only for professionals ({n})"),
                        _t(lang, f"它意味着忽略感受（{n}）", f"It means ignoring feelings ({n})"),
                    ],
                    "correct_index": 0,
                    "explanation": _t(
                        lang,
                        "这个技能的重点是停下来、注意、再选择。",
                        "The point of the skill is to pause, notice, and then choose.",
                    ),
                }
                for n in range(1, 4)
            ]
        }
    elif f == "generate_hint":
        out = {
            "hint": _t(
                lang,
                "再看一看题目里提到的第一个线索。",
                "Look again at the first clue in the task.",
            )
        }
    elif f == "personalize_feedback":
        out = {
            "feedback": _t(
                lang,
                "你在这一步里做出了选择，下一步可以再试一次。",
                "You made a choice in this step; you can try the next one again.",
            )
        }
    elif f == "assess_risk":
        # Mirrors the keyword tier so CI behaves like keyword-only screening.
        tier = request.hints.get("keyword_tier")
        high = tier == "high"
        out = {
            "risk_level": "high" if high else ("medium" if tier else "none"),
            "categories": ["risk_disclosure"] if tier else [],
            "should_stop": high,
            "reasoning": "mock",
        }
    else:
        out = {}
    return json.dumps({**base, **out}, ensure_ascii=False)
