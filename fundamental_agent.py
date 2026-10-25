"""
2-QISM: Fundamental Agent — PRO v4.0 Haqiqiy Makro + Jonli Kapital Oqimi (Order-Flow) Tahlilchisi (fundamental_agent.py)
PRO v4.0 MUHIM TUZATISHLARI (Kecha kechqurungi 3 ta SL sababi 100% bartaraf etildi!):
1) Dam olish kunlari (Shanba/Yakshanba) DXY va US10Y bozori YOPIQ (Juma kungi shamchada qotib qolgan) bo'ladi!
   Eski versiyada qotib qolgan DXY=BULLISH va Juma kungi Oltin sarlavhasi sababli bot BTCUSD $1,600 tepaga
   o'sayotganda ham (`79,314 -> 80,900`, `VWAP 80,009` dan `$740` tepada!) ko'r-ko'rona `BEARISH (SELL)` beravergan!
2) Endi Fundamental Agent 3 ta haqiqiy kuchni birgalikda his qiladi:
   - A) Yangilikning asl ma'nosi (Inflyatsiya/Stavka oshishi vs Geosiyosiy urush/Safe-Haven vs Kripto Short-Squeeze/ETF Inflow).
   - B) Jonli Kapital Oqimi (Real-Time Money Flow): Agar yangilik eski/aralash bo'lsa-yu, yirik fondlar jonli bozorda
     narxni Intraday VWAP va H1/M15 EMA20/50 ustiga katta hajm (`RVOL > 1.3x`) bilan olib chiqib, oldingi cho'qqini
     buzgan bo'lsa — bot buni **Institutsional Xarid / Short-Squeeze (`BULLISH`)** deb tan oladi va o'sayotgan bozorga qarshi `SELL` bermaydi!
   - C) Agar Fundamental yangiliklar bilan Jonli Kapital Oqimi bir-biriga zid kelsa, bot soxta signal bermasdan
     `NEUTRAL (KUTISH)` beradi!
"""
from datetime import datetime, timezone, timedelta
import json
import logging
from typing import Optional

from config import GEMINI_API_KEY, GEMINI_MODEL, TIMEZONE_OFFSET_HOURS
from schemas import MarketSnapshot, FundamentalSignal
from news_scraper import MacroNewsScraper

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class FundamentalAgent:
    """
    PRO v4.0 Haqiqiy Makroiqtisodiy Voqealar Zanjiri + Jonli Institutsional Kapital Oqimi Tahlilchisi.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: str = GEMINI_MODEL):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name
        self.client = None
        if GENAI_AVAILABLE and self.api_key and self.api_key != "your_gemini_api_key":
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Gemini Client ishga tushmadi: {e}")

    @staticmethod
    def _analyze_live_institutional_flow(snapshot: MarketSnapshot) -> dict[str, float | str | bool]:
        """
        Grafikdagi jonli pul oqimini (Real-Time Institutional Order Flow) hisoblaydi:
        Yirik o'yinchilar haqiqatda sotayaptimi yoki sotib olyaptimi?
        """
        ltf = snapshot.ltf_df.iloc[:-1] if len(snapshot.ltf_df) > 40 else snapshot.ltf_df
        htf = snapshot.htf_df.iloc[:-1] if len(snapshot.htf_df) > 40 else snapshot.htf_df
        cp = float(snapshot.current_price)
        atr = max(float(snapshot.atr), 1.0)

        # 1) Intraday VWAP va RVOL
        sub36 = ltf.tail(36)
        typical = (sub36["high"] + sub36["low"] + sub36["close"]) / 3.0
        vol = sub36["volume"].replace(0, 1.0)
        vwap = float((typical * vol).sum() / vol.sum())
        rvol = round(float(vol.tail(8).max() / max(vol.mean(), 1.0)), 2)

        # 2) M15 va H1 EMA tuzilmasi
        m15_ema20 = float(ltf["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        m15_ema50 = float(ltf["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        h1_ema20 = float(htf["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        h1_ema50 = float(htf["close"].ewm(span=50, adjust=False).mean().iloc[-1])

        # 3) Oxirgi 12 ta M15 shamcha (3 soat) va 24 ta shamcha (6 soat) strukturasi
        w_old = sub36.iloc[:20]
        w_new = sub36.iloc[20:]
        old_high = float(w_old["high"].max())
        old_low = float(w_old["low"].min())
        new_high = float(w_new["high"].max())
        new_low = float(w_new["low"].min())

        # Bullish BOS (masalan kechagi 80,802.96 > 80,781.41 va narx VWAP 80,009 dan tepada!)
        broke_high_upward = (new_high > old_high) and (cp > vwap + 0.15 * atr)
        strong_pump_above_vwap = (cp > vwap + 0.50 * atr) and (m15_ema20 > m15_ema50)

        # Bearish BOS (yangi minimum va narx VWAP dan pastda)
        broke_low_downward = (new_low < old_low) and (cp < vwap - 0.15 * atr)
        strong_dump_below_vwap = (cp < vwap - 0.50 * atr) and (m15_ema20 < m15_ema50)

        flow_score = 0.0
        if broke_high_upward or strong_pump_above_vwap:
            flow_score += 0.55
        elif cp > vwap and m15_ema20 >= m15_ema50:
            flow_score += 0.30

        if broke_low_downward or strong_dump_below_vwap:
            flow_score -= 0.55
        elif cp < vwap and m15_ema20 <= m15_ema50:
            flow_score -= 0.30

        if cp > h1_ema20:
            flow_score += 0.20
        else:
            flow_score -= 0.20

        flow_dir = "BULLISH" if flow_score >= 0.25 else ("BEARISH" if flow_score <= -0.25 else "NEUTRAL")
        return {
            "flow_dir": flow_dir,
            "flow_score": round(flow_score, 2),
            "vwap": round(vwap, 2),
            "rvol": rvol,
            "m15_ema20": round(m15_ema20, 2),
            "m15_ema50": round(m15_ema50, 2),
            "h1_ema20": round(h1_ema20, 2),
            "h1_ema50": round(h1_ema50, 2),
            "broke_high_upward": broke_high_upward or strong_pump_above_vwap,
            "broke_low_downward": broke_low_downward or strong_dump_below_vwap,
        }

    def analyze(
        self,
        snapshot: MarketSnapshot,
        headlines: list[str],
        high_impact_imminent: bool = False
    ) -> FundamentalSignal:
        entity_context = MacroNewsScraper.extract_entities_and_context(headlines)
        flow = self._analyze_live_institutional_flow(snapshot)

        system_prompt = (
            "Sen Global Macro Hedge-Fund bosh tahlilchisi va Smart Money Strategsan. "
            "Vazifang XAUUSD (Oltin) va BTCUSD uchun yangiliklarni VA jonli kapital oqimini (VWAP, EMA20/50, Order-Flow) "
            "birlashtirib, bozordagi HAQIQIY yo'nalishni va keyingi qadamni (Next Move) topishdir.\n"
            "MUHIM QOIDA: Agar yangiliklar eski yoki zaif bo'lsa-yu, jonli narx VWAP va M15 EMA20/50 dan ancha tepada "
            "yangi cho'qqilarni buzib o'sayotgan bo'lsa (Bullish Order-Flow / Short-Squeeze), HECH QACHON BEARISH berma! "
            "Aksincha, agar yangiliklar bilan texnik kapital oqimi bir-biriga zid bo'lsa, bias='NEUTRAL' va confidence_score=0.10 qaytar.\n\n"
            "Javobni FAQAT quyidagi JSON sxemasida (o'zbek tilida) qaytar:\n"
            "{\n"
            '  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",\n'
            '  "confidence_score": float (-1.0 dan +1.0 gacha),\n'
            '  "macro_reason": "2-3 gapda aniq fundamental va kapital oqimi xulosasi",\n'
            '  "causal_chain": "1-Voqea -> 2-Kapital oqimi -> 3-Institutlar harakati -> 4-Keyingi likvidlik maqsadi",\n'
            '  "key_actors_analysis": ["Ishtirokchi 1 harakati", "Ishtirokchi 2 harakati"],\n'
            '  "geopolitical_hotspots": ["Hudud 1 ta\'siri", "Hudud 2 ta\'siri"],\n'
            '  "predicted_next_moves": ["Asosiy Ssenariy", "Muqobil Ssenariy (Bekor bo\'lish sharti)"],\n'
            '  "key_drivers": ["Driver 1", "Driver 2"]\n'
            "}"
        )

        user_prompt = (
            f"Aktiv: {snapshot.symbol}\n"
            f"Joriy narx: {snapshot.current_price}\n"
            f"Intraday VWAP: {flow['vwap']} (Joriy narx VWAP dan {'TEPADА - Xarid oqimi' if snapshot.current_price > flow['vwap'] else 'PASTDA - Sotuv bosimi'})\n"
            f"M15 EMA20: {flow['m15_ema20']} | M15 EMA50: {flow['m15_ema50']} | H1 EMA20: {flow['h1_ema20']} | H1 EMA50: {flow['h1_ema50']}\n"
            f"Jonli Order-Flow Yo'nalishi: {flow['flow_dir']} ({flow['flow_score']:+.2f})\n"
            f"DXY H1 trendi: {snapshot.dxy_trend} | US10Y H1 trendi: {snapshot.us10y_trend}\n"
            f"FXStreet sarlavhalari:\n- " + "\n- ".join(headlines)
        )

        if self.client is not None:
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                data = json.loads(response.text)
                return FundamentalSignal(
                    symbol=snapshot.symbol,
                    bias=str(data.get("bias", "NEUTRAL")).upper(),
                    confidence_score=round(float(data.get("confidence_score", 0.0)), 2),
                    macro_reason=str(data.get("macro_reason", "Makroiqtisodiy tahlil yakunlandi.")),
                    high_impact_news_imminent=high_impact_imminent,
                    key_drivers=list(data.get("key_drivers", [])),
                    causal_chain=str(data.get("causal_chain", "")),
                    key_actors_analysis=list(data.get("key_actors_analysis", [])),
                    geopolitical_hotspots=list(data.get("geopolitical_hotspots", [])),
                    predicted_next_moves=list(data.get("predicted_next_moves", [])),
                )
            except Exception as e:
                logger.warning(f"Gemini API xatosi, PRO v4.0 Causal-Graph + Order-Flow dvigateliga o'tilmoqda: {e}")

        return self._dynamic_rule_based_macro_logic(snapshot, headlines, high_impact_imminent, entity_context, flow)

    def _dynamic_rule_based_macro_logic(
        self,
        snapshot: MarketSnapshot,
        headlines: list[str],
        high_impact_imminent: bool,
        entity_context: Optional[dict[str, list[str]]] = None,
        flow: Optional[dict] = None,
    ) -> FundamentalSignal:
        flow = flow or self._analyze_live_institutional_flow(snapshot)
        is_btc = "BTC" in snapshot.symbol.upper()
        tashkent_now = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS)))
        is_weekend = tashkent_now.weekday() in (5, 6)

        # 1) FXStreet sarlavhalarini aktivga mos tahlil qilish (Gold sarlavhasi BTC ni aldamasligi uchun!)
        relevant_headlines: list[str] = []
        for h in headlines:
            hl = h.lower()
            if is_btc and ("gold" in hl or "xau" in hl) and not any(k in hl for k in ("bitcoin", "btc", "crypto", "fed", "fomc", "dxy", "cpi", "yield")):
                continue
            relevant_headlines.append(h)
        if not relevant_headlines:
            relevant_headlines = headlines

        text_blob = " ".join(relevant_headlines).lower()
        top_headline = relevant_headlines[0] if relevant_headlines else "Institutional Order-Flow & Macro Liquidity Update"
        second_headline = relevant_headlines[1] if len(relevant_headlines) > 1 else top_headline

        macro_score = 0.0
        drivers: list[str] = []

        # Dam olish kunlari (Shanba/Yakshanba) DXY va US10Y bozori yopiq bo'ladi — ularni BTC uchun asosiy drayver qilmaymiz!
        if not (is_btc and is_weekend):
            if snapshot.dxy_trend == "BEARISH":
                macro_score += 0.30
                drivers.append("DXY H1 pasayish trendida")
            elif snapshot.dxy_trend == "BULLISH":
                macro_score -= 0.30
                drivers.append("DXY H1 o'sish trendida")

            if snapshot.us10y_trend == "BEARISH":
                macro_score += 0.20
                drivers.append("US10Y obligatsiya daromadliligi pasaymoqda (Risk-On / Oltin va BTC uchun ijobiy)")
            elif snapshot.us10y_trend == "BULLISH":
                macro_score -= 0.20
                drivers.append("US10Y obligatsiya daromadliligi o'smoqda (Dolllarga oqim)")

        bullish_words = (
            "rate cut", "dovish", "misses", "cooler cpi", "dollar retreats", "dollar slips",
            "safe-haven demand", "rallies", "climbs", "rebounds", "picks up", "bullish",
            "inflows", "etf inflow", "short-squeeze", "breaks above", "surges"
        )
        bearish_words = (
            "hike bets", "80%", "rate hike", "hawkish", "cap gains", "stalls", "slides",
            "falls", "rout", "bears still in control", "stronger usd", "usd uptick",
            "outflows", "sell-off", "drops below"
        )

        bull_hits = sum(1 for w in bullish_words if w in text_blob)
        bear_hits = sum(1 for w in bearish_words if w in text_blob)

        if bear_hits > bull_hits:
            macro_score -= min(0.30, 0.12 * (bear_hits - bull_hits))
        elif bull_hits > bear_hits:
            macro_score += min(0.30, 0.12 * (bull_hits - bear_hits))

        # 2) ENG MUHIM HIMOYA: Jonli Kapital Oqimi (Order-Flow) bilan Makro uyg'unligini tekshirish!
        # Agar narx VWAP dan ancha tepada yangi cho'qqilarni buzib o'sayotgan bo'lsa (masalan kechagi 80,745 > VWAP 80,009),
        # eski Bearish sarlavha sababli SELL berish QAT'IYAN MAN ETILADI!
        flow_score = float(flow["flow_score"])
        cp = round(snapshot.current_price, 2)
        vwap = float(flow["vwap"])

        if flow["broke_high_upward"]:
            # Bozor amalda kuchli Bullish Breakout / Short-Squeeze qilmoqda!
            if macro_score < -0.20 and not is_weekend:
                # Makro Bearish, lekin narx kuchli Bullish -> Qarama-qarshilik (KUTISH / NEUTRAL)
                final_score = 0.15
                bias = "NEUTRAL"
            else:
                final_score = max(0.65, round(flow_score + max(0.0, macro_score), 2))
                bias = "BULLISH"
                drivers.append(f"Jonli Kapital Oqimi: Narx ({cp:.2f}) VWAP ({vwap:.2f}) va lokal cho'qqini yorib o'tdi (Bullish Impulse)")
        elif flow["broke_low_downward"]:
            # Bozor amalda kuchli Bearish Breakdown qilmoqda!
            if macro_score > 0.20 and not is_weekend:
                final_score = -0.15
                bias = "NEUTRAL"
            else:
                final_score = min(-0.65, round(flow_score + min(0.0, macro_score), 2))
                bias = "BEARISH"
                drivers.append(f"Jonli Kapital Oqimi: Narx ({cp:.2f}) VWAP ({vwap:.2f}) ostida kuchli sotuv bosimida")
        else:
            combined = round(0.55 * flow_score + 0.45 * macro_score, 2)
            if abs(combined) < 0.35:
                final_score = combined
                bias = "NEUTRAL"
            elif combined > 0:
                final_score = max(0.55, min(0.95, combined + 0.15))
                bias = "BULLISH"
            else:
                final_score = min(-0.55, max(-0.95, combined - 0.15))
                bias = "BEARISH"

        final_score = max(-1.0, min(1.0, round(final_score, 2)))

        atr = max(snapshot.atr, 8.5 if "XAU" in snapshot.symbol.upper() else 250.0)
        down_target_1 = round(cp - 1.2 * atr, 2)
        down_target_2 = round(cp - 2.2 * atr, 2)
        up_target_1 = round(cp + 1.2 * atr, 2)
        up_target_2 = round(cp + 2.2 * atr, 2)

        actors = (entity_context or {}).get("actors", []) or [
            "Fed / FOMC (Warsh & Powell)",
            "Wall Street Institutsional Fondlari (BlackRock / Spot ETF / CME)",
        ]
        locations = (entity_context or {}).get("locations", []) or [
            "AQSh (Vashington / Nyu-York — Wall Street, CME & Fed)",
        ]

        if bias == "BEARISH":
            causal_chain = (
                f"1 FXStreet asosiy voqeasi: «{top_headline}» ➡️ "
                f"2 Qo'shimcha drayver: «{second_headline}» ➡️ "
                f"3 {', '.join(actors[:2])} tomonidan qat'iy (Hawkish) likvidlik nazorati ➡️ "
                f"4 Cross-Asset & Order-Flow Tasdiq: DXY ({snapshot.dxy_trend}), US10Y ({snapshot.us10y_trend}) hamda narxning VWAP (`{vwap:.2f}`) ostida sotuv bosimida qolishi ➡️ "
                f"5 {snapshot.symbol} ning joriy `{cp:.2f}` darajasidan `{down_target_1:.2f}` va `{down_target_2:.2f}` likvidlik hovuzlariga tushish harakati."
            )
            reason = (
                f"FXStreet yangiliklar oqimi («{top_headline[:75]}...»), DXY ({snapshot.dxy_trend}) va jonli Order-Flow "
                f"(narx `{cp:.2f}` < VWAP `{vwap:.2f}`, M15 EMA20 `{flow['m15_ema20']:.2f}`) yirik ishtirokchilarning "
                f"{snapshot.symbol} da sotuv (Distribution) pozitsiyasida ekanini tasdiqlab, kuchli Bearish ({final_score:+.2f}) bosim bermoqda."
            )
            next_moves = [
                f"Asosiy Ssenariy (Bearish davomi): Yirik fondlar `{cp:.2f}–{up_target_1:.2f}` oralig'idagi sotuv (Supply) zonasidan narxni `{down_target_1:.2f}` va `{down_target_2:.2f}` dagi Sell-Side likvidlik hovuzlarigacha tushirishga harakat qiladi.",
                f"Muqobil Ssenariy (Reversal sharti): Agar `{up_target_1:.2f}` va VWAP (`{vwap:.2f}`) ustida M15/H1 shamcha yopilsa, Bearish ssenariy bekor qilinib Short-Squeeze boshlanadi (shu sababli SL va Bezubitok qoidasi majburiy)."
            ]
        elif bias == "BULLISH":
            causal_chain = (
                f"1 Asosiy Bozor Drayveri: «{top_headline}» ➡️ "
                f"2 Jonli Kapital Oqimi: {snapshot.symbol} ning `{vwap:.2f}` (Intraday VWAP) va `{flow['m15_ema50']:.2f}` (EMA50) ustida `{flow['rvol']}x` hajm bilan yorib chiqishi ➡️ "
                f"3 {', '.join(actors[:2])} tomonidan pastki likvidlik yig'ilib (Accumulation / Short-Squeeze), xarid orderlarining faollashishi ➡️ "
                f"4 {snapshot.symbol} ning `{cp:.2f}` darajasidan `{up_target_1:.2f}` va `{up_target_2:.2f}` Buy-Side likvidlik (BSL) hovuzlariga o'sish harakati."
            )
            reason = (
                f"Jonli Order-Flow tahlili (Joriy narx `{cp:.2f}` > Intraday VWAP `{vwap:.2f}`, RVOL `{flow['rvol']}x`) va "
                f"makroiqtisodiy fon («{top_headline[:75]}...») yirik institutsional xaridorlarning bozorni nazoratga olganini "
                f"ko'rsatib, {snapshot.symbol} ga kuchli Bullish ({final_score:+.2f}) impuls bermoqda."
            )
            next_moves = [
                f"Asosiy Ssenariy (Bullish davomi): Yirik fondlar `{down_target_1:.2f}–{cp:.2f}` oralig'idagi xarid (Demand / Breaker) zonasidan narxni `{up_target_1:.2f}` va `{up_target_2:.2f}` dagi Buy-Side likvidlik hovuzlarigacha olib chiqishga harakat qiladi.",
                f"Muqobil Ssenariy (Reversal sharti): Agar narx VWAP (`{vwap:.2f}`) va `{down_target_1:.2f}` tayanchidan pastda H1 shamcha yopsa, o'sish impulsi to'xtaydi (SL va Bezubitok qoidasi majburiy)."
            ]
        else:
            causal_chain = (
                f"1 FXStreet sarlavhasi («{top_headline[:65]}...») va Jonli Order-Flow (`{cp:.2f}` vs VWAP `{vwap:.2f}`) o'rtasida qarama-qarshilik mavjud ➡️ "
                f"2 Yirik fondlar yangi impuls oldidan likvidlik yig'moqda (Consolidation) ➡️ "
                f"3 Aniq Breakout/CHoCH tasdiqlanmaguncha bozorga kirish taqiqlanadi."
            )
            reason = (
                f"Makroiqtisodiy fon va M15/H1 texnik kapital oqimi bir-birini tasdiqlamadi (Score: {final_score:+.2f}). "
                f"SL yemaslik uchun bot aniq institutsional yo'nalish chiqishini kutmoqda."
            )
            next_moves = [
                f"Kutish rejimi: `{up_target_1:.2f}` ustida yopilsa Bullish, `{down_target_1:.2f}` ostida yopilsa Bearish setup ochiladi."
            ]

        key_actors_analysis = [f"{act}: Joriy bozor oqimida {bias} yo'nalishdagi asosiy institutsional ishtirokchi." for act in actors]
        geopolitical_hotspots = [f"{loc}: Faol makroiqtisodiy va likvidlik markazi." for loc in locations]

        return FundamentalSignal(
            symbol=snapshot.symbol,
            bias=bias,
            confidence_score=final_score,
            macro_reason=reason,
            high_impact_news_imminent=high_impact_imminent,
            key_drivers=drivers,
            causal_chain=causal_chain,
            key_actors_analysis=key_actors_analysis,
            geopolitical_hotspots=geopolitical_hotspots,
            predicted_next_moves=next_moves,
        )