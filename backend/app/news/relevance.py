"""Is a GDELT "gold" article about gold as a market? (finding C, 2026-11-07)

GDELT matches its query against machine translations of whole articles in ~65 languages, so a bare "gold"
returns anything golden: of 250 articles of the old query on 2026-11-07, about 15–20 were about the gold
market; the rest were medals, a Greek island ("Chrysi"), a Slovak choir, recipes, crime. FTI therefore
  1. asks GDELT for gold together with a market word (gdelt.QUERIES["gold"]) — this works in every language,
     because GDELT applies it to the translated text;
  2. checks the title itself: it must name gold, and, in a language FTI has a vocabulary for, also a market
     context (price, ounce, investors, central bank, mining …). In a language without a vocabulary the title
     only has to name gold; the market context is then vouched for by the query (step 1).
Nothing is restricted to English: about twenty languages are read, the rest pass on step 1.
"""

from __future__ import annotations

import re

# gold, in the languages and scripts GDELT returns most (not: gold medal/coast/cup, golden …, the zloty currency)
GOLD = re.compile(
    r"\bgold(?:preis\w*|kurs\w*|markt\w*|barren|reserven|minen\w*|anleger)?\b(?![\s-]+(?:coast|medals?|medallist|cup)\b)"
    r"|\bbullion\b|\bxau\b|\bzlat\w*|\bzłot(?!y\b|ych\b|ówk)\w*|\boro\b|\bouro\b|\bl['’]or\b|\bgoud\b|\bguld\b|\bgull\b"
    r"|\bkulta\w*|\barany\b|\baur(?:ului|ul)?\b|\baltın\w*|\baltin\w*|\bemas\b"
    r"|黄金|黃金|金价|金價|金価格|金相場|ذهب|الذهب|सोना|सोने|गोल्ड|সোনা|স্বর্ণ|золот\w*|χρυσ\w*|ทองคำ|금값|זהב|طلا",
    re.IGNORECASE,
)
_MEDALS = re.compile(r"medall\w* de oro|medaglia d['’]oro|zlat\w* medail\w*|medail\w* zlat\w*|medalha de ouro", re.IGNORECASE)

_EN = (r"\bprices?\b|\bpriced\b|\bounces?\b|\boz\b|\$|\busd\b|\bdollars?\b|\bfutures\b|\bcomex\b|\bmcx\b|\bspot\b|\betfs?\b"
       r"|\bfunds?\b|\bmarkets?\b|\btrad\w*|\binvest\w*|\brall(?:y|ies)\b|\brecord\b|\brates?\b|\bfed\b|\binflation\b"
       r"|\byields?\b|\btreasur\w*|\bcentral banks?\b|\breserves?\b|\bmin(?:e|es|ing|ers?)\b|\bcommodit\w*|\bmetals?\b"
       r"|\bdemand\b|\bhaven\b|\btola\b|\bgrams?\b|\b[kc]arat\b|\bstocks?\b|\bshares?\b|\beconom\w*|\bloans?\b"
       r"|\bimports?\b|\bexports?\b|\btariffs?\b|\btonnes?\b|\bhedge\b|\bbull\w*|\bbear\w*|\bsupports?\b|\bresistance\b"
       r"|\bforecast\w*|\boutlook\b|\banalys\w*|\btechnical\b|\bhighs?\b|\blows?\b|\bweekly\b|\blosses?\b|\bpayrolls?\b"
       r"|\brbi\b|\bjewel\w*|\bbuy\w*|\bsell\w*|\b(?:rise|rises|rose|rising|fall|falls|fell|falling|gain|gains|slip|slips"
       r"|drop|drops|jump|jumps|climb|climbs|surge|surges|steady|steadies|ease|eases|dip|dips|slide|slides|plunge|plunges"
       r"|soar|soars|tumble|tumbles|rebound\w*|retreat\w*)\b")
_SLAVIC = (r"\bcen\w*|\bunc\w*|\btrh\w*|\bburz\w*|\binvest\w*|\bdolar\w*|\bkurz\w*|\brekord\w*|\bcentráln\w*|\bbank\w*"
           r"|\brezerv\w*|\btěž\w*|\bťaž\w*|\bkomodit\w*|\bkov\w*|\binflac\w*|\bsazb\w*|\bsadzb\w*|\bnákup\w*|\bnakup\w*"
           r"|\bprodej\w*|\bpredaj\w*|\bzdraž\w*|\bzlevn\w*|\bzlacn\w*|\bpokles\w*|\bvýnos\w*|\bakci\w*|\bcijen\w*"
           r"|\btržiš\w*|\bkopal\w*|\bsurow\w*|\binwest\w*|\bgiełd\w*|\buncj\w*")
CONTEXT = {
    "English": _EN,
    "Czech": _SLAVIC, "Slovak": _SLAVIC, "Croatian": _SLAVIC, "Serbian": _SLAVIC, "Slovenian": _SLAVIC,
    "Bosnian": _SLAVIC, "Polish": _SLAVIC,
    "German": r"preis|kurs|unze|aktie|anleger|notenbank|zentralbank|markt|börse|inflation|zins|dollar|rekord|reserve|mine|rohstoff|edelmetall|anlage|invest|barren|\bfed\b|\betf",
    "Spanish": r"precio|onza|mercado|bolsa|inversi|banco central|reservas|\bmina|miner|materias primas|dólar|inflaci|\btasa|récord|cotiza|lingote|tonelada",
    "Portuguese": r"preço|onça|mercado|bolsa|invest|banco central|reservas|\bmina|miner|commodit|dólar|inflação|juros|recorde|cotação|lingote|tonelada",
    "Italian": r"prezz|oncia|mercat|borsa|invest|banca centrale|riserve|minier|materie prime|dollar|inflazion|tass|record|quotazion|lingott|tonnellat",
    "French": r"\bprix\b|\bonce\b|\bcours\b|bourse|marché|investiss|banque centrale|réserves|\bmine|minier|matières premières|dollar|inflation|\btaux\b|record|lingot|tonnes",
    "Dutch": r"prijs|koers|\bons\b|beurs|belegg|centrale bank|reserves|\bmijn|grondstof|dollar|inflatie|rente|record",
    "Swedish": r"pris|kurs|\buns|börs|invest|centralbank|reserver|gruva|råvar|dollar|inflation|ränta|rekord",
    "Norwegian": r"pris|kurs|\bunse|børs|invest|sentralbank|reserver|gruve|råvar|dollar|inflasjon|rente|rekord",
    "Danish": r"pris|kurs|\bunse|børs|invest|centralbank|reserver|\bmine|råvar|dollar|inflation|rente|rekord",
    "Finnish": r"hinta|hinna|unssi|pörssi|sijoit|keskuspankki|kaivos|dollari|inflaatio|korko|markkin",
    "Hungarian": r"\bár\b|árfolyam|uncia|tőzsde|befektet|jegybank|tartalék|bány|dollár|infláció|kamat|rekord",
    "Romanian": r"preț|pret|uncie|bursă|bursa|invest|banca centrală|rezerv|\bmin|dolar|inflați|dobând|record",
    "Turkish": r"fiyat|\bgram|\bons\b|\btl\b|dolar|yatırım|piyasa|seviye|hedef|merkez bankası|rezerv|maden|enflasyon|faiz|rekor|borsa|çeyrek",
    "Indonesian": r"harga|\bons\b|\bgram|investasi|bank sentral|cadangan|tambang|dolar|inflasi|suku bunga|rekor|antam",
    "Malay": r"harga|\bauns|\bgram|pelaburan|bank pusat|rizab|lombong|dolar|inflasi|kadar faedah|rekod",
    "Russian": r"цен|унци|рын|бирж|инвест|центробанк|центральн\w* банк|резерв|добыч|рудник|доллар|инфляц|ставк|рекорд|котировк|фьючерс",
    "Ukrainian": r"цін|унці|рин|бірж|інвест|резерв|видобут|долар|інфляц|ставк|рекорд|котирув",
    "Greek": r"τιμ(?:ή|ής|ές|ών)|ουγγι|αγορ|χρηματιστ|επενδ|κεντρικ\w* τράπεζ|αποθεμ|ορυχ|δολάρ|πληθωρισμ|επιτόκ|ρεκόρ",
    "Chinese": r"价|價|盎司|美元|央行|储备|儲備|矿|礦|期货|期貨|投资|投資|行情|市场|市場|金市|点金|點金",
    "Arabic": r"سعر|أسعار|اسعار|الأونصة|أوقية|دولار|البنك المركزي|احتياطي|منجم|استثمار|سوق|أسواق|جرام|غرام|شراء|بيع|عيار",
    "Hindi": r"कीमत|दाम|भाव|रेट|निवेश|बाजार|बाज़ार|ग्राम|आरबीआई|\brbi\b|लोन|डॉलर|price|etf",
    "Marathi": r"दर|किंमत|भाव|गुंतवणूक|बाजार|ग्रॅम|price",
    "Bengali": r"দাম|মূল্য|বাজার|বিনিয়োগ|ভরি|গ্রাম|ডলার|রিজার্ভ",
}
_CONTEXT = {k: re.compile(v, re.IGNORECASE) for k, v in CONTEXT.items()}
_EN_RX = _CONTEXT["English"]


def gold_market(title: str, language: str | None) -> tuple[bool, str]:
    """(keep?, why) for an article the GDELT "gold" query returned. `language` is GDELT's language name."""
    if not GOLD.search(_MEDALS.sub(" ", title)):
        return False, "titulek není o zlatě"
    ctx = _CONTEXT.get(language or "English")
    if ctx is None:
        return True, f"jazyk bez slovníku FTI ({language}) — souvislost s trhem ověřil dotaz GDELT"
    if ctx.search(title) or _EN_RX.search(title):
        return True, "zlato + souvislost s trhem v titulku"
    return False, "zlato bez souvislosti s trhem (medaile, šperk, jméno …)"
