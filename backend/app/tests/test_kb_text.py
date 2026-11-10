"""Knowledge-base text handling (Plan §5.3 steps 2, 4, 5): pure functions, no database."""

from __future__ import annotations

from app.kb import text as kbtext
from app.tests.kb_fixtures import FOOTER, FOOTER_EN, SIDE_TAB


def test_clean_page_drops_footers_side_tabs_and_furniture() -> None:
    page = "\n".join(
        [FOOTER, "正念讲义1", *SIDE_TAB, "1.", "第一项内容", "完成日：", "（续下页）", FOOTER_EN]
    )
    assert kbtext.clean_page(page) == ["正念讲义1", "1.", "第一项内容"]


def test_frequent_long_lines_are_footers_but_short_list_markers_are_kept() -> None:
    pages = [f"重复出现的很长的页脚文字行\n1.\n第{i}页内容" for i in range(8)]
    frequent = kbtext.frequent_lines(pages)
    assert frequent == {"重复出现的很长的页脚文字行"}
    assert kbtext.clean_page(pages[0], frequent) == ["1.", "第0页内容"]


def test_merge_lines_rejoins_wrapped_sentences_only() -> None:
    lines = [
        "这是一句被PDF在中间折断的很长很长很长的句子，它的后半部分在",
        "下一行继续。",
        "标题",
        "1. 列表项不会被合并",
    ]
    assert kbtext.merge_lines(lines) == [
        "这是一句被PDF在中间折断的很长很长很长的句子，它的后半部分在下一行继续。",
        "标题",
        "1. 列表项不会被合并",
    ]


def test_header_variants_and_index_titles() -> None:
    assert kbtext.find_header(["正念讲义3"]) == ("mf.h3", 0)
    assert kbtext.find_header(["正文", "人际效能手册8"]) == ("ie.h8", 1)
    assert kbtext.find_header(["走 在 中 道 上 4"]) == ("wmp.h4", 0)
    assert kbtext.find_header(["情绪调节讲义16a 标题"]) == ("er.h16a", 0)
    assert kbtext.find_header(["情绪调节很重要，第3点"]) is None
    assert kbtext.index_titles(["痛苦忍受讲义11：危机技能", "无关的行"]) == {"dt.h11": "危机技能"}


def test_chunks_respect_size_and_carry_pages() -> None:
    paras = [
        (f"第{i}句：这是一段用于测试分块的中文句子，长度大约三十个字符。", 3 + i // 20)
        for i in range(60)
    ]
    chunks = kbtext.chunk_handout(paras)
    assert len(chunks) > 1
    assert all(len(c.text) <= kbtext.CHUNK_MAX + kbtext.OVERLAP_MAX for c in chunks)
    assert all(len(c.text) >= kbtext.CHUNK_MIN // 2 for c in chunks)
    assert chunks[0].pages[0] == 3 and chunks[-1].pages[-1] == 5
    joined = "\n".join(c.text for c in chunks)
    assert all(p in joined for p, _ in paras)  # nothing lost


def test_oversized_paragraph_is_split() -> None:
    chunks = kbtext.chunk_handout([("很" * 1500, 9)])
    assert all(len(c.text) <= kbtext.CHUNK_MAX for c in chunks)
    assert sum(len(c.text) for c in chunks) == 1500


def test_short_handout_is_one_chunk() -> None:
    assert [c.text for c in kbtext.chunk_handout([("短讲义", 1)])] == ["短讲义"]


def test_tokens_keep_dbt_terms_and_drop_stop_words() -> None:
    kbtext.init_tokenizer(["智慧心念"])
    toks = kbtext.tokens("我的智慧心念和DEAR MAN技能")
    assert "智慧心念" in toks and "dear" in toks and "man" in toks
    assert "的" not in toks and "和" not in toks


def test_english_queries_use_only_acronyms_for_keywords() -> None:
    # The manual is Chinese: ordinary English words would only match stray labels.
    assert kbtext.query_tokens("how do I ask with DEAR MAN skills", "en") == ["dear", "man"]
    assert kbtext.query_tokens("feeling angry at my mum", "en") == []


def test_tsquery_text_is_sanitised() -> None:
    toks = kbtext.tokens("it's a 'quote' & | ! (test) 呼吸:*")
    q = kbtext.tsquery_text(toks)
    inner = q.replace("' | '", "").strip("'")
    assert inner.isalnum()  # no tsquery operators or quotes can come from user text
    assert q.count("'") == 2 * len(set(toks))


def test_side_tab_header_is_kept_once() -> None:
    page = "\n".join(["走", "在", "中", "道", "上", "7", "7", "正文第一行内容"])
    assert kbtext.clean_page(page) == ["走在中道上7", "正文第一行内容"]
    assert kbtext.find_header(kbtext.clean_page(page)) == ("wmp.h7", 0)
