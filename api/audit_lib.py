import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from itertools import combinations
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (compatible; seo-saas/1.0)"}
ARTICLE_HINTS = ("/blog", "/article", "/post", "/news", "/guide", "/مقال", "/مدونة")
SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|pdf|zip|mp4|mp3|css|js|xml)(\?|$)", re.I)
STOP = set("""a an the and or but if of to in on at for from by with about as is are was were be been it this
that these those you your we our they their he she his her i me my not no yes do does did can will just so than
then too very into over under how what when where which who why more most some any all also have has had
في من على إلى الى عن مع هذا هذه ذلك تلك هو هي هم هن أن ان إن كان كانت يكون ما ماذا كيف متى أين لماذا هل لا نعم
أو و ثم لكن قد كل بعض أي الذي التي الذين عند بين حتى بعد قبل أكثر أقل""".split())
SPLIT = re.compile(r"[.!?؟،,;:\n()\[\]\"«»|–—-]+")


def fetch(url, timeout=12):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
    except requests.RequestException:
        return None
    return r.content if r.status_code == 200 else None


def sitemap_urls(base, cap=500):
    urls, queue, seen = [], [urljoin(base, "/sitemap.xml")], set()
    while queue and len(urls) < cap:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        xml = fetch(sm)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            continue
        for el in root.iter():
            if el.tag.endswith("loc") and el.text:
                u = el.text.strip()
                (queue if u.endswith(".xml") else urls).append(u)
    return urls


def ngrams(text, nmax=3):
    c = Counter()
    for seg in SPLIT.split(text.lower()):
        toks = [None if (w in STOP or len(w) < 3 or w.isdigit()) else w
                for w in re.findall(r"\w+", seg)]
        for n in range(1, nmax + 1):
            for i in range(len(toks) - n + 1):
                g = toks[i:i + n]
                if None not in g:
                    c[" ".join(g)] += 1
    return c


def pick(counts, exclude, k):
    ranked = sorted(counts.items(), key=lambda x: (-x[1] * (1 + 0.6 * (len(x[0].split()) - 1)), x[0]))
    chosen = []
    for g, c in ranked:
        if c < 2 or g in exclude:
            continue
        if any(g in s or s in g for s in chosen + list(exclude)):
            continue
        chosen.append(g)
        if len(chosen) == k:
            break
    return chosen


def extract(url, html):
    soup = BeautifulSoup(html, "html.parser")
    links = [urljoin(url, a["href"]) for a in soup.find_all("a", href=True)]

    def meta(name=None, prop=None):
        tag = soup.find("meta", attrs={"name": name} if name else {"property": prop})
        return (tag.get("content") or "").strip() if tag else ""

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(" ", strip=True) if h1_tag else ""
    path = urlparse(url).path.lower()
    depth = len([s for s in path.split("/") if s])
    is_article = (meta(prop="og:type") == "article"
                  or len(soup.find_all("article")) == 1
                  or (depth >= 2 and any(h in path for h in ARTICLE_HINTS)))
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        t.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    body = root.get_text(" ", strip=True)
    words = len(body.split())
    if not is_article or words < 200:
        return None, links

    counts = ngrams(body)
    strong = ngrams("%s. %s" % (title, h1))
    cands = strong or counts
    primary = max(cands, key=lambda g: ((counts.get(g, 0) + 1) * (1, 2.5, 3)[len(g.split()) - 1], g))
    secondary = pick(counts, {primary}, 6)
    return {"url": url, "title": title, "h1": h1, "word_count": words,
            "primary_keyword": primary, "secondary_keywords": secondary}, links


def crawl_site(base, limit=20, time_budget=50, delay=0.3):
    if not base.startswith("http"):
        base = "https://" + base
    host = urlparse(base).netloc
    rp = RobotFileParser(urljoin(base, "/robots.txt"))
    try:
        rp.read()
    except Exception:
        pass
    allowed = lambda u: rp.can_fetch("*", u) if rp.last_checked else True

    queue = [u for u in sitemap_urls(base) if urlparse(u).netloc == host] or [base]
    seen, pages, fetched = set(), [], 0
    start = time.time()
    while queue and fetched < limit and (time.time() - start) < time_budget:
        url = urldefrag(queue.pop(0))[0]
        if url in seen or SKIP_EXT.search(url) or not allowed(url):
            continue
        seen.add(url)
        html = fetch(url)
        fetched += 1
        time.sleep(delay)
        if not html:
            continue
        page, links = extract(url, html)
        if page:
            pages.append(page)
        for l in links:
            p = urlparse(l)
            if p.scheme in ("http", "https") and p.netloc == host:
                queue.append(l)
    return pages, fetched


GENERIC_WORDS = set("""ترجمة الترجمة translation الرسمية المعتمدة معتمدة معتمد مكتب مكاتب office offices
جالينوس galenus official certified professional documents document services service accurate quality
حيث وذلك لضمان بدقة بسرعة الخدمات خدمات شركة مصر egypt""".split())
GENERIC_PRIMARIES = {"ترجمة", "translation", "الترجمة"}


def dwordset(p):
    words = {w.lower() for phrase in [p["primary_keyword"], *p["secondary_keywords"]] for w in phrase.split()}
    return words - STOP - GENERIC_WORDS


def fullwordset(p):
    return {w.lower() for phrase in [p["primary_keyword"], *p["secondary_keywords"]] for w in phrase.split()}


def remainder(text, kw):
    return text.replace(kw, "").strip()


def same_angle(a, b, pa, pb):
    ta = ((a.get("title") or "") + " " + (a.get("h1") or "")).strip()
    tb = ((b.get("title") or "") + " " + (b.get("h1") or "")).strip()
    ra, rb = remainder(ta, pa), remainder(tb, pb)
    if not ra or not rb:
        return True
    if ra in rb or rb in ra:
        return True
    wa, wb = set(ra.split()), set(rb.split())
    return len(wa & wb) / len(wa | wb) >= 0.5 if wa | wb else True


def title_sim(a, b):
    ta = ((a.get("title") or "") + " " + (a.get("h1") or "")).strip()
    tb = ((b.get("title") or "") + " " + (b.get("h1") or "")).strip()
    return SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0.0


def _jacc(x, y):
    return len(x & y) / len(x | y) if x | y else 0


def find_conflicts(pages):
    rows, variations = [], []
    for a, b in combinations(pages, 2):
        pa, pb = a["primary_keyword"], b["primary_keyword"]
        if not pa or not pb:
            continue
        ratio = SequenceMatcher(None, pa, pb).ratio()
        da, db = dwordset(a), dwordset(b)
        shared = len(da & db)
        t = title_sim(a, b)
        sj = _jacc({w for ph in a["secondary_keywords"] for w in ph.lower().split()},
                   {w for ph in b["secondary_keywords"] for w in ph.lower().split()})
        generic = pa in GENERIC_PRIMARIES or pb in GENERIC_PRIMARIES
        note = ("كلمة عامة: كل صفحة تحتاج استهدافا محددا (مستند/لغة/منطقة)"
                if generic else "long-tail من نفس الـ short-tail بزوايا مختلفة: تبقى كما هي")
        if pa == pb:
            angle = same_angle(a, b, pa, pb)
            if t >= 0.75 or shared >= 3 or sj >= 0.5:
                if not angle and shared <= 1 and sj < 0.3:
                    variations.append({"keyword_a": pa, "keyword_b": pb,
                                       "url_a": a["url"], "url_b": b["url"], "note": note})
                else:
                    rows.append({"severity": "high", "type": "same_primary_keyword",
                                 "keyword_a": pa, "keyword_b": pb,
                                 "url_a": a["url"], "url_b": b["url"], "similarity": round(max(ratio, sj), 2)})
            elif t >= 0.55 or shared >= 2:
                if not angle and shared <= 1:
                    variations.append({"keyword_a": pa, "keyword_b": pb,
                                       "url_a": a["url"], "url_b": b["url"], "note": note})
                else:
                    rows.append({"severity": "medium", "type": "similar_angle",
                                 "keyword_a": pa, "keyword_b": pb,
                                 "url_a": a["url"], "url_b": b["url"], "similarity": round(max(ratio, sj), 2)})
            else:
                variations.append({"keyword_a": pa, "keyword_b": pb,
                                   "url_a": a["url"], "url_b": b["url"], "note": note})
        elif ratio >= 0.8 or pa in pb or pb in pa:
            angle = same_angle(a, b, pa, pb)
            if shared >= 2 or t >= 0.55 or sj >= 0.4:
                if not angle and shared <= 1 and sj < 0.3:
                    variations.append({"keyword_a": pa, "keyword_b": pb,
                                       "url_a": a["url"], "url_b": b["url"], "note": note})
                else:
                    rows.append({"severity": "medium", "type": "similar_primary_keyword",
                                 "keyword_a": pa, "keyword_b": pb,
                                 "url_a": a["url"], "url_b": b["url"], "similarity": round(max(ratio, sj), 2)})
            else:
                variations.append({"keyword_a": pa, "keyword_b": pb,
                                   "url_a": a["url"], "url_b": b["url"], "note": note})
        else:
            wa, wb = fullwordset(a), fullwordset(b)
            if _jacc(wa, wb) >= 0.5:
                if shared >= 3:
                    rows.append({"severity": "low", "type": "overlapping_keyword_sets",
                                 "keyword_a": pa, "keyword_b": pb,
                                 "url_a": a["url"], "url_b": b["url"], "similarity": round(_jacc(wa, wb), 2)})
                elif _jacc(wa, wb) >= 0.6:
                    variations.append({"keyword_a": pa, "keyword_b": pb,
                                       "url_a": a["url"], "url_b": b["url"],
                                       "note": "تشابه مفردات عامة فقط: لا إجراء"})
    rank = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (rank[r["severity"]], -r["similarity"]))
    return rows, variations


def intent_for(p):
    t = (p.get("title") or "") + " " + (p.get("h1") or "") + " " + (p.get("primary_keyword") or "")
    info_keys = ["الفرق", "دليل", "دليلك", "كيفية", "لماذا", "أهمية",
                 "Difference", "How to Choose", "Which Is Better", "توطين", "شروط "]
    trans_keys = ["أفضل", "Best", "عاجل", "سريع", "Fast", "فوري", "أسعار", "تكلفة",
                  "أونلاين", "اونلاين", "مغاغة", "الدقي", "الجيزة", "القاهرة",
                  "مصر الجديدة", "جدة", "الرياض", "الإمارات", "وسط البلد"]
    if any(k in t for k in info_keys):
        return "informational"
    if any(k in t for k in trans_keys):
        return "transactional"
    return "commercial"


def group_conflicts(conflicts, max_groups=15):
    from collections import defaultdict
    groups = defaultdict(list)
    for r in conflicts:
        groups[(r["severity"], r["keyword_a"])].append(r)
    out = []
    for (sev, kw), rs in sorted(groups.items(), key=lambda x: ({"high": 0, "medium": 1, "low": 2}[x[0][0]], -len(x[1]))):
        urls = sorted({r["url_a"] for r in rs} | {r["url_b"] for r in rs})
        out.append({"severity": sev, "keyword": kw, "count": len(urls), "urls": urls})
        if len(out) >= max_groups:
            break
    return out


def fix_for(keyword):
    if keyword in ("ترجمة", "translation", "الترجمة"):
        return "كلمة عامة جدا. أعد استهداف كل صفحة بكلمة محددة (مستند أو لغة) واجعل الكلمة العامة صفحة محورية تربط للكل."
    if keyword in ("مكتب ترجمة معتمد", "مكاتب ترجمة معتمدة"):
        return "صفحات مناطق بنفس الكلمة. ميز كل صفحة (عنوان وهاتف وخريطة للمنطقة) أو ادمج في صفحة دليل واحدة مع canonical."
    if keyword == "عقد التأسيس للشركات":
        return "تكرار حرفي. ادمج في صفحة واحدة شاملة مع تحويلات 301 من المكرر."
    return "نفس الكلمة على أكثر من صفحة. ميز الاستهداف (مستند أو لغة أو جهة) واربط بين الصفحات داخليا بدل التنافس."
