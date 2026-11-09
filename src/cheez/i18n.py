"""Interface strings in English, Traditional Chinese and Simplified Chinese.

Editorial text is translated by the writer (see ``editorial/translate.py``);
this module covers the page's own labels. Each localisable element is rendered
in the edition's language and carries the other versions as ``data-*``
attributes, so the reader can switch language on the page without a reload and
the page still reads correctly with scripts off.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from markupsafe import Markup, escape

LANGS = ("en", "zh-Hant", "zh-Hans")
ATTR = {"en": "data-en", "zh-Hant": "data-zh-hant", "zh-Hans": "data-zh-hans"}
HTML_LANG = {"en": "en-GB", "zh-Hant": "zh-Hant", "zh-Hans": "zh-Hans"}

# English -> (Traditional, Simplified). Keys are the English text as written in templates.
UI: dict[str, tuple[str, str]] = {
    # navigation and sections
    "Today": ("今日", "今日"),
    "Playbook": ("交易清單", "交易清单"),
    "Today's playbook": ("今日交易清單", "今日交易清单"),
    "The few names worth acting on today, at a glance": ("今天值得行動的少數標的，一眼看完", "今天值得行动的少数标的，一眼看完"),
    "Brief": ("要聞", "要闻"),
    "The brief": ("今日要聞", "今日要闻"),
    "What matters, in order": ("依重要性排序", "依重要性排序"),
    "Markets": ("市場", "市场"),
    "Levels and changes with the session each comes from": ("各項報價及其交易時段", "各项报价及其交易时段"),
    "In focus": ("焦點", "焦点"),
    "Stocks in focus": ("焦點個股", "焦点个股"),
    "Chosen on today's evidence, independent of your holdings": ("依今日證據挑選，與持倉無關", "依今日证据挑选，与持仓无关"),
    "Ideas": ("觀點", "观点"),
    "Decisions and ideas": ("決策與投資觀點", "决策与投资观点"),
    "Long-only, cash account · research, not orders": ("只做多、現金帳戶 · 研究觀點，不是下單指令", "只做多、现金账户 · 研究观点，不是下单指令"),
    "Portfolio": ("持倉", "持仓"),
    "Your portfolio": ("你的持倉", "你的持仓"),
    "Coming up": ("即將發生", "即将发生"),
    "Events that could move prices": ("可能影響價格的事件", "可能影响价格的事件"),
    "Record": ("紀錄", "记录"),
    "Idea record": ("觀點紀錄", "观点记录"),
    "Every published idea, unedited, with what happened next": ("每個已發布觀點，原文保留，並追蹤後續", "每个已发布观点，原文保留，并追踪后续"),
    "Sources and method": ("資料來源與方法", "数据来源与方法"),
    "Archive": ("歸檔", "归档"),
    "Settings": ("設定", "设置"),
    # masthead
    "In 30 seconds": ("30 秒看懂", "30 秒看懂"),
    "Published": ("發布", "发布"),
    "Data cut-off": ("資料截至", "数据截至"),
    "minute read": ("分鐘閱讀", "分钟阅读"),
    "Complete": ("完整", "完整"),
    "Partial data": ("部分資料", "部分数据"),
    "Market closed": ("休市", "休市"),
    "Demonstration": ("示範", "示范"),
    "Revision": ("修訂版", "修订版"),
    "Since the last edition": ("自上期以來", "自上期以来"),
    "Why it matters.": ("為何重要。", "为何重要。"),
    "Not yet known:": ("尚不清楚：", "尚不清楚："),
    "Established": ("已確認", "已确认"),
    "Developing": ("發展中", "发展中"),
    "Uncertain": ("不確定", "不确定"),
    "Hypothesis": ("假設", "假设"),
    # playbook card
    "Why": ("理由", "理由"),
    "Outlook": ("展望", "展望"),
    "Entry zone": ("進場區間", "进场区间"),
    "Invalidation": ("失效價位", "失效价位"),
    "Target": ("目標", "目标"),
    "Reward ÷ risk": ("報酬 ÷ 風險", "回报 ÷ 风险"),
    "Last": ("最新", "最新"),
    "1 month": ("1 個月", "1 个月"),
    "3 months": ("3 個月", "3 个月"),
    "vs 52-week high": ("距 52 週高點", "距 52 周高点"),
    "Full reasoning": ("完整分析", "完整分析"),
    "You hold this": ("你持有", "你持有"),
    "Decision for today": ("今日決策", "今日决策"),
    "Not for today": ("非今日", "非今日"),
    "Follow-up": ("追蹤", "追踪"),
    "Revised view": ("觀點修訂", "观点修订"),
    "Low confidence": ("信心：低", "信心：低"),
    "Moderate confidence": ("信心：中", "信心：中"),
    "High confidence": ("信心：高", "信心：高"),
    "No trade today": ("今日不交易", "今日不交易"),
    "On the radar": ("觀察名單", "观察名单"),
    "Conditional research plans, not orders. Levels are not guaranteed prices: markets can gap through them.":
        ("以下為有條件的研究計畫，不是下單指令。價位不保證成交：市場可能跳空穿越。",
         "以下为有条件的研究计划，不是下单指令。价位不保证成交：市场可能跳空穿越。"),
    "3-month daily close": ("近 3 個月日收盤", "近 3 个月日收盘"),
    # actions
    "Consider buying": ("考慮買入", "考虑买入"),
    "Consider adding": ("考慮加碼", "考虑加仓"),
    "Hold": ("持有", "持有"),
    "Consider trimming": ("考慮減碼", "考虑减仓"),
    "Consider exiting": ("考慮出場", "考虑离场"),
    "Wait": ("等待", "等待"),
    "Watch": ("觀察", "观察"),
    # idea detail
    "Why now": ("為何是現在", "为何是现在"),
    "Catalyst": ("催化因素", "催化因素"),
    "Value or trap?": ("價值還是陷阱？", "价值还是陷阱？"),
    "What changed": ("有何改變", "有何改变"),
    "Before acting": ("行動之前", "行动之前"),
    "Strongest case against": ("最強反方論點", "最强反方论点"),
    "Would change our view": ("什麼會改變我們的看法", "什么会改变我们的看法"),
    "Confidence basis": ("信心依據", "信心依据"),
    "Feasibility": ("可行性", "可行性"),
    "Reassess the thesis": ("重新評估論點", "重新评估论点"),
    "Computed, not forecast": ("計算值，非預測", "计算值，非预测"),
    "Why it deserves attention": ("值得關注的原因", "值得关注的原因"),
    "Our read": ("我們的解讀", "我们的解读"),
    "Notes on the moves": ("走勢備註", "走势备注"),
    "No compelling setup today": ("今日沒有足夠好的機會", "今日没有足够好的机会"),
    "Nothing else clears the bar": ("其他標的未達標準", "其他标的未达标准"),
    "This is a conditional research idea, not an instruction to place an order. Cheez never places, changes or cancels orders. Levels are not guaranteed execution prices: prices can gap through them.":
        ("這是有條件的研究觀點，不是下單指令。Cheez 從不下單、改單或撤單。價位不是保證成交價：價格可能跳空穿越。",
         "这是有条件的研究观点，不是下单指令。Cheez 从不下单、改单或撤单。价位不是保证成交价：价格可能跳空穿越。"),
    # markets
    "Instrument": ("標的", "标的"),
    "Level": ("報價", "报价"),
    "Change": ("漲跌", "涨跌"),
    "Trend": ("走勢", "走势"),
    "United States": ("美國", "美国"),
    "Europe": ("歐洲", "欧洲"),
    "Asia": ("亞洲", "亚洲"),
    "Rates": ("利率", "利率"),
    "Currencies": ("匯率", "汇率"),
    "Commodities": ("大宗商品", "大宗商品"),
    # portfolio
    "Cash by currency": ("各幣別現金", "各币种现金"),
    "What today means for your holdings": ("今天對你持倉的意義", "今天对你持仓的意义"),
    "How today's ideas would fit": ("今日觀點如何配合現有持倉", "今日观点如何配合现有持仓"),
    "Open orders (read-only view)": ("未成交訂單（唯讀）", "未成交订单（只读）"),
    # settings panel
    "Language": ("語言", "语言"),
    "Also show prices in": ("同時以此貨幣顯示價格", "同时以此货币显示价格"),
    "Off": ("關閉", "关闭"),
    "Theme": ("外觀", "外观"),
    "Auto": ("自動", "自动"),
    "Light": ("淺色", "浅色"),
    "Dark": ("深色", "深色"),
    "Done": ("完成", "完成"),
    "Conversions are approximate, at the rates shown, and for reading only.":
        ("換算為近似值，按所示匯率計算，僅供閱讀參考。", "换算为近似值，按所示汇率计算，仅供阅读参考。"),
    "Translation not available for this edition; showing English.":
        ("本期沒有此語言的翻譯，顯示英文。", "本期没有此语言的翻译，显示英文。"),
}

WEEKDAYS = {
    "zh-Hant": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
    "zh-Hans": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
}


def ui_text(en: str, lang: str) -> str:
    if lang == "en" or en not in UI:
        return en
    return UI[en][0 if lang == "zh-Hant" else 1]


def long_date(d: date, lang: str) -> str:
    if lang == "en":
        return d.strftime("%A %-d %B %Y")
    return f"{d.year}年{d.month}月{d.day}日 {WEEKDAYS[lang][d.weekday()]}"


def span(versions: Mapping[str, str], lang: str, *, html: bool = False, langs: tuple[str, ...] = LANGS) -> Markup:
    """An inline element showing ``versions[lang]`` (falling back to English)
    that carries the other languages for the on-page switch. With ``html``
    the versions are already-escaped markup."""
    en = versions["en"]
    shown = versions.get(lang) or en
    shown_m = Markup(shown) if html else escape(shown)
    others = {k: v for k, v in versions.items() if k in langs and v}
    if len(others) <= 1:
        return shown_m
    attrs = " ".join(f'{ATTR[k]}="{escape(v)}"' for k, v in others.items())
    kind = "h" if html else "t"
    return Markup(f'<span data-i18n="{kind}" {attrs}>') + shown_m + Markup("</span>")


def ui(en: str, lang: str, langs: tuple[str, ...] = LANGS) -> Markup:
    if en not in UI:
        return escape(en)
    t, s = UI[en]
    return span({"en": en, "zh-Hant": t, "zh-Hans": s}, lang, langs=langs)
