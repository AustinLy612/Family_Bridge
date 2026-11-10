"""A small synthetic "manual" for knowledge-base tests: fictional text, no manual content.

Seven pages: an index page, a divider, and five content pages for four handouts. It reproduces
the real manual's quirks: copyright footers, a vertical side tab, worksheet furniture, a
diagram page with no text layer (read from a transcription), and a page whose printed header
number disagrees with the index.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.content.models import HandoutIndex

FOOTER = "本手册仅允许购买人士为个人用途进行影印（详情请参阅版权页)。"
FOOTER_EN = "From DBT® Skills Manual for Adolescents, by Test Author. Copyright 2015 by Test Press."
SIDE_TAB = ["走", "在", "中", "道", "上"]

BREATH = [
    f"第{i}条：注意呼吸时身体的感觉，然后轻轻地把注意力带回到当下这一刻。" for i in range(1, 31)
]

PAGES: list[list[str]] = [
    # 1: index (table of contents)
    [
        "测试手册目录",
        "导论讲义1：家庭练习小组是什么",
        "正念讲义1：观察呼吸的练习",
        "正念讲义2：三个圆圈的图示",
        "人际效能讲义1：提出请求的方法",
    ],
    # 2: divider
    ["正念"],
    # 3: ori.h1
    [
        FOOTER,
        "导论讲义1",
        "家庭练习小组是什么？",
        *SIDE_TAB,
        "小组每周见面一次，家长和青少年一起学习新的应对方法，并在家里完成练习作业，",
        "下一次见面时大家分享练习中遇到的困难。",
        "完成日：",
        FOOTER_EN,
    ],
    # 4-5: mf.h1 (two pages, long enough for several chunks)
    [FOOTER, "正念讲义1", "观察呼吸的练习", *BREATH[:15], FOOTER_EN],
    [FOOTER, *BREATH[15:], "（续下页）", FOOTER_EN],
    # 6: mf.h2, a diagram page: no usable text layer
    [FOOTER],
    # 7: ie.h1, but the page prints the wrong number (like the real manual's pages 106, 111-113)
    [
        FOOTER,
        "人际效能讲义3",
        "提出请求的方法",
        "DEAR MAN 帮助你清楚地描述情况，表达感受，坚定地提出请求，并说明对方答应后的好处。",
        "练习时先写下你想要的结果，再想一想对方可能的回应。",
        FOOTER_EN,
    ],
]

TRANSCRIPTION = """---
page: 6
handout: mf.h2
source_quality: manual_transcription
transcribed_by: test
---
正念讲义2 三个圆圈的图示
（图示：两个重叠的圆圈，重叠处是第三个区域。）
重叠的区域代表把思考和感受结合在一起的状态。
"""


def handout_index() -> HandoutIndex:
    return HandoutIndex.model_validate(
        {
            "kind": "handout_index",
            "version": 1,
            "approval": {"status": "draft"},
            "source": {"pdf_pages": 7, "index_pages": [1], "divider_pages": [2]},
            "handouts": [
                {
                    "id": "ori.h1",
                    "module": "orientation",
                    "number": "1",
                    "title_en": "What the family practice group is",
                    "pages": [3],
                    "skill_ids": ["ori.what_is_dbt"],
                },
                {
                    "id": "mf.h1",
                    "module": "mindfulness",
                    "number": "1",
                    "title_en": "Practising observing the breath",
                    "pages": [4, 5],
                    "skill_ids": ["mf.what_skills"],
                },
                {
                    "id": "mf.h2",
                    "module": "mindfulness",
                    "number": "2",
                    "title_en": "Diagram of three circles",
                    "pages": [6],
                    "skill_ids": ["mf.states_of_mind"],
                    "diagram_pages": [6],
                },
                {
                    "id": "ie.h1",
                    "module": "interpersonal_effectiveness",
                    "number": "1",
                    "title_en": "How to ask for something",
                    "pages": [7],
                    "skill_ids": ["ie.dear_man"],
                },
            ],
        }
    )


def write_pdf(path: Path) -> Path:
    import pymupdf

    doc: Any = pymupdf.open()  # type: ignore[no-untyped-call]
    for lines in PAGES:
        page = doc.new_page()
        page.insert_text((40, 60), "\n".join(lines), fontname="china-s", fontsize=9)
    doc.save(path)
    doc.close()
    return path


def write_transcriptions(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "p006.md").write_text(TRANSCRIPTION, encoding="utf-8")
    return directory
