"""Regenerate fixtures/demo/editorial.zh-Hant.json and .zh-Hans.json.

Developer tool only (needs `pip install opencc-python-reimplemented`). The
Traditional text below is hand-written; Simplified is converted with OpenCC
(Taiwan-to-mainland phrases) and then saved. Re-run after editing the English
demo editorial; every English prose string must have an entry, in order.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cheez.editorial.translate import is_fixed  # noqa: E402

HANT = [
    "示範：晶片供應疑慮緩解，消費類股持續走低",
    "這是一份以合成資料與虛構公司製作的示範版。它展示 Cheez 如何安排一個早晨的內容：少數真正重要的發展、跨資產概覽、兩檔值得關注的個股，以及附有價位、條件與反方論點的排序觀點。",
    "Northwind（虛構）表示晶片封裝交期再度縮短；股價在下跌 20% 後於盤前反彈。",
    "必需消費品因銷量停滯持續下跌：變便宜不等於更有價值。",
    "交易清單：等待 Northwind 回落至 158–166，檢視過大的 Harbourline 持倉，Meridian 續抱但不加碼。",
    "一家虛構晶片商表示產能短缺正在緩解",
    "Northwind Semiconductor（虛構）在示範研討會上表示，其先進封裝產線的交期連續第二個月縮短。股價自 9 月高點下跌 20% 後，今天盤前走高。",
    "若產能正在放寬，原本限量供貨的公司會失去部分定價能力，而等待晶片的客戶可以出貨更多。對設備供應商的影響，取決於緩解是來自新增設備還是需求轉弱。",
    "公司沒有提供訂單數字，因此供應緩解也可能反映需求轉弱，而非產能增加。",
    "示範研討會逐字稿",
    "示範來源",
    "必需消費品因銷量成長停滯而持續走弱",
    "Meridian Consumer Brands（虛構）已自 52 週高點下跌約 26%。兩家示範同業上週公布的銷售量持平，成長完全來自漲價。",
    "以漲價帶動的成長，往往在消費者轉向較便宜選擇後消退。股價變便宜只有在銷量穩定時才有幫助；在那之前，下跌可能反映的是未來獲利降低，而非暫時性的賣壓。",
    "示範同業財報摘要",
    "美債殖利率在示範就業報告公布前小幅走高",
    "合成的 10 年期殖利率今晨小幅上升。虛構的就業報告將於週五公布。",
    "殖利率上升會提高長存續期成長股的折現率。單日變動幅度很小；未來一週的方向更重要。",
    "示範經濟行事曆",
    "合成的美股期貨顯示開盤平穩，歐洲漲跌互見，亞洲收低。跨資產走勢與上述個股消息沒有矛盾，但也沒有提供佐證。",
    "期貨在現貨指數開盤前就會變動；其漲跌是相對於前一結算價，而非昨日指數收盤。",
    "前一交易日的官方收盤殖利率；下方的即時列是盤中替代指標。",
    "與新聞同時發生的走勢，並不能證明是新聞造成的。",
    "第一期示範版：沒有更早的版本可供比較。",
    "Northwind 公布產能更新後盤前反彈",
    "管理層表示封裝交期連續第二個月縮短（虛構）。",
    "股價比 9 月高點低 20%，接近 10 月的波段低點，因此這次更新出現在市場預期已經下修的時點。",
    "這番說法方向上有幫助，但內容單薄。沒有訂單數據，還無法區分是供應改善還是需求轉弱。",
    "Quartzline Equipment（虛構）",
    "Quartzline 銷售封裝設備。若 Northwind 增購設備，Quartzline 已入帳這些訂單；若交期縮短是因需求放緩，未來的設備訂單可能轉弱。",
    "示範文件將 Northwind 列為前五大客戶之一，因此無論哪種情況，這個關聯都很重要。",
    "Quartzline 股價幾乎沒動，顯示投資人在等待它自己的訂單數據。",
    "示範供應商申報文件",
    "3–6 個月",
    "供應正在緩解，股價距高點已跌 20%；回落至 10 月低點會是比今天反彈更好的進場時機。",
    "若 11 月 19 日的財報確認訂單健康，三個月內回到 50 日均線（約 $188）附近是合理的。",
    "回落至 10 月低點附近，可能為一家供應限制或正在緩解的企業提供更好的進場點。",
    "股價已自 9 月高點下跌約 20%，而公司自己的更新顯示供應正在改善。等待價格進入區間，可避免追逐單日反彈。",
    "11 月 19 日的財報應能顯示訂單是否支持產能方面的說法。",
    "區間從 20 日低點（165.92）稍下方，延伸到 7 月波段低點上方缺口的中段。10 月波段低點 170.62 是其上方最近的支撐；回到區間內，等於重新測試近期區間的底部，而非 9 月高點。",
    "價格以收盤價為準（不只是盤中）落在 158–166 之間。",
    "11 月 19 日財報沒有下修財測；若財報先公布，之後再重新評估區間。",
    "屆時買賣價差維持正常（在此示範中，該股每日成交額約 $1.9bn）。",
    "跌破 200 日均線（150.34）與 7 月波段低點（150.22）後，長期上升趨勢將被破壞，這次回檔看起來會更像趨勢反轉。",
    "財報後股價可能直接開在此價位之下，因此這是重新評估的點，而不是保證的出場價。",
    "基本情境",
    "約 3 個月",
    "若財報確認供應緩解且訂單沒有轉弱，股價回到 50 日均線。",
    "樂觀情境",
    "約 6 個月",
    "若訂單加速，股價重新測試 9 月高點。",
    "11 月 19 日的財報落在持有期間內，可能使股價朝任一方向大幅波動。",
    "以港幣現金買入美元計價股票，會增加換匯成本。",
    "半導體股往往同漲同跌；這會增加既有的晶片曝險。",
    "從外部看，交期縮短正是需求放緩的樣子。如果客戶下單減少，20% 的跌幅可能是下行週期的開始，而不是買進機會。",
    "出現訂單下滑或 11 月 19 日下修財測的證據；收盤跌破 149.50。",
    "從高點下跌本身並不代表有價值。這裡區分回檔與陷阱的關鍵是訂單數據；在財報公布前，這個區間只是有條件的進場點，並非認定股價便宜。",
    "公司自己的說法支持此論點，但關鍵證據（訂單）尚未公布。",
    "本週內檢視",
    "經過長期上漲，Harbourline 現在佔示範帳戶一半以上。",
    "不做價格判斷：問題在於單一公司應該在多大程度上左右帳戶的結果。",
    "單一持股現在佔示範帳戶一半以上，因此帳戶的表現主要取決於一家公司。",
    "股價在穩定上漲後接近 52 週高點，因此這個部位在沒有任何決策的情況下，佔帳戶的比重變大了。",
    "沒有公司事件即將發生；觸發因素是集中度，而不是新聞。",
    "先決定你能接受的單一公司比重；在設定風險偏好之前，Cheez 不會建議部位大小。",
    "賣出前先確認此帳戶以外的稅務狀況，這是 Cheez 看不到的。",
    "賣出上漲中的股票，可能意味著放棄進一步的漲幅。",
    "手續費與資本利得稅會降低效益。",
    "公司經營良好，也沒有出問題。單純為了平衡而減碼贏家，若趨勢延續，可能降低報酬。",
    "如果你決定集中持股是刻意的安排，這就變成「持有」。",
    "集中度直接由帳戶計算；多少算太多，取決於 Cheez 尚未取得的偏好設定。",
    "示範帳戶快照",
    "直到銷量數據公布",
    "銷量停滯，因此較低的股價可能反映的是較低的獲利，而不是便宜貨。",
    "在銷量穩定之前，股價可能在 8 至 9 月低點附近區間整理。",
    "持有但不加碼：下跌看來是銷量停滯所致，這會降低未來獲利，因此較低的價格還不算便宜。",
    "股價接近 8 至 9 月的低點（約 33.6–34.0），也就是先前買盤進場的區域。",
    "下一季的銷量數據；同業對消費降級的評論。",
    "在考慮加碼之前，先觀察銷售量是否停止下滑。",
    "若 33.6 附近的低點失守，下一個參考位是 52 週低點 32.79。",
    "擁有強勢品牌的必需消費品公司，常在漲價效應滿一年後恢復，而且股價已反映了大量利空。",
    "連續兩季銷量穩定，會讓較低的價格更具吸引力；若下修財測，出場的理由會更充分。",
    "有價值陷阱的風險：股價較便宜，但原因（銷量下滑）會直接降低獲利。",
    "證據來自同業，而非 Meridian 本身。",
    "示範帳戶的持股集中：Harbourline 佔一半以上，其次是一檔港股與 Meridian。現金分為美元與港幣，只有美元現金能在不換匯的情況下買入美股。",
    "接近 52 週高點；是集中度的主要來源。",
    "券商沒有提供成本價，因此不顯示損益。",
    "加入 Northwind 會為目前沒有半導體曝險的帳戶增加此類曝險；若以新資金買入，也會降低 Harbourline 的比重。",
    "Quartzline 那筆 55 的未成交買單高於目前股價；請確認它仍符合你的意圖。",
    "示範就業報告",
    "利率與成長股對勞動市場的意外變化很敏感。",
    "Northwind 財報（虛構）",
    "檢驗觀點 1 背後的產能論點。",
    "示範內容：本頁所有公司、數字與來源連結皆為虛構。",
]

# Mainland usage after character conversion.
HANS_FIX = {"財測": "业绩指引", "财测": "业绩指引", "加碼": "加仓", "加码": "加仓", "減碼": "减仓", "减码": "减仓",
            "殖利率": "收益率", "曝險": "敞口", "曝险": "敞口", "港幣": "港币", "部位": "仓位", "帐户": "账户", "进场": "入场", "於": "于"}


def strings(obj, fixed=False, out=None, parent=""):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            strings(v, fixed or is_fixed(k, parent), out, k)
    elif isinstance(obj, list):
        for v in obj:
            strings(v, fixed, out, parent)
    elif isinstance(obj, str) and not fixed and obj not in out:
        out.append(obj)
    return out


def replace(obj, mapping, fixed=False, parent=""):
    if isinstance(obj, dict):
        return {k: replace(v, mapping, fixed or is_fixed(k, parent), k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace(v, mapping, fixed, parent) for v in obj]
    if isinstance(obj, str) and not fixed:
        return mapping[obj]
    return obj


def main() -> None:
    import opencc

    src = ROOT / "fixtures" / "demo" / "editorial.json"
    en = json.loads(src.read_text())
    keys = strings(en)
    if len(keys) != len(HANT):
        sys.exit(f"{len(keys)} English strings but {len(HANT)} translations")
    hant = dict(zip(keys, HANT))
    t2s = opencc.OpenCC("tw2sp")
    hans = {}
    for k, v in hant.items():
        s = t2s.convert(v)
        for a, b in HANS_FIX.items():
            s = s.replace(a, b)
        hans[k] = s
    for lang, m in (("zh-Hant", hant), ("zh-Hans", hans)):
        out = ROOT / "fixtures" / "demo" / f"editorial.{lang}.json"
        out.write_text(json.dumps(replace(en, m), ensure_ascii=False, indent=1) + "\n")
        print("wrote", out)


if __name__ == "__main__":
    main()
