import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, render_template

from audit_lib import crawl_site, find_conflicts, group_conflicts, intent_for, fix_for
from wp_lib import WPClient, WPError
from ai_lib import seo_title, meta_desc, rewrite_article, new_article, AIError

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))


@app.get("/")
def home():
    return render_template("index.html", error=None)


@app.post("/audit")
def audit():
    site = (request.form.get("site") or "").strip()
    try:
        limit = max(5, min(int(request.form.get("limit") or 20), 40))
    except ValueError:
        limit = 20
    if not site:
        return render_template("index.html", error="دخل لينك الموقع الأول")
    pages, fetched = crawl_site(site, limit=limit, time_budget=50, delay=0.3)
    conflicts, variations = find_conflicts(pages)
    for p in pages:
        p["intent"] = intent_for(p)
        try:
            p["slug"] = p["url"].split(".com/")[1].strip("/")
        except IndexError:
            p["slug"] = p["url"]
    groups = group_conflicts(conflicts)
    for g in groups:
        g["fix"] = fix_for(g["keyword"])
    junk = sum(1 for p in pages if p["primary_keyword"] in ("ترجمة", "translation", "الترجمة"))
    return render_template("report.html", site=site, pages=pages, fetched=fetched,
                           conflicts=conflicts, variations=variations, groups=groups, junk=junk)


@app.get("/health")
def health():
    return {"ok": True}


def wp_client():
    base = os.environ.get("WP_URL", "")
    user = os.environ.get("WP_USER", "")
    pw = os.environ.get("WP_APP_PASSWORD", "")
    if not (base and user and pw):
        return None
    return WPClient(base, user, pw)


@app.get("/wp")
def wp_home():
    ai_ok = bool(os.environ.get("AI_API_KEY"))
    c = wp_client()
    posts, status = [], None
    if c is None:
        status = "غير متصل: اضبط WP_URL و WP_USER و WP_APP_PASSWORD في متغيرات البيئة"
    else:
        try:
            ok, name = c.check()
            status = ("متصل: " + name) if ok else "فشل الاتصال: " + name
            if ok:
                posts = c.posts()
        except Exception as e:
            status = "خطأ: " + str(e)
    return render_template("wp.html", status=status, posts=posts, ai_ok=ai_ok, result=None)


@app.post("/wp/run")
def wp_run():
    action = request.form.get("action")
    mode = request.form.get("mode", "draft")
    result = {"action": action, "ok": False, "messages": [], "link": ""}
    try:
        c = wp_client()
        if c is None:
            raise WPError("بيانات وردبريس غير مضبوطة")
        if action == "new_article":
            kw = (request.form.get("keyword") or "").strip()
            intent = request.form.get("intent", "commercial")
            if not kw:
                raise WPError("اكتب الكلمة المستهدفة")
            title = seo_title(kw, kw)
            content = new_article(kw, intent)
            pid, link = c.create_post(title, content, status="publish" if mode == "publish" else "draft")
            result["messages"].append("اتعمل مقال جديد رقم %s بحالة %s" % (pid, mode))
            result["link"] = link
            result["ok"] = True
        else:
            pid = int(request.form.get("post_id"))
            p = c.get_post(pid)
            kw = (request.form.get("keyword") or "").strip() or p["title"][:60]
            if action == "fix_title":
                new_title = seo_title(kw, p["title"])
                c.update_post(pid, {"title": new_title})
                result["messages"].append("العنوان القديم: " + p["title"][:80])
                result["messages"].append("العنوان الجديد: " + new_title)
                result["ok"] = True
            elif action == "fix_meta":
                desc = meta_desc(kw)
                saved = []
                if c.try_meta(pid, "_yoast_wpseo_metadesc", desc):
                    saved.append("Yoast")
                if c.try_meta(pid, "rank_math_description", desc):
                    saved.append("RankMath")
                if saved:
                    result["messages"].append("اتحفظ الوصف في: " + " و".join(saved))
                else:
                    result["messages"].append("مفيش إضافة SEO مكشوفة للـ API. انسخ الوصف يدوي: " + desc)
                result["messages"].append("الوصف: " + desc)
                result["ok"] = True
            elif action == "rewrite_content":
                html = rewrite_article(kw, p["content"])
                keep = {"content": html}
                if mode == "publish" and p["status"] == "draft":
                    keep["status"] = "publish"
                c.update_post(pid, keep)
                result["messages"].append("اتعدل المحتوى (النسخة القديمة محفوظة في مراجعات وردبريس)")
                result["ok"] = True
            result["link"] = p.get("link", "")
    except (WPError, AIError, ValueError) as e:
        result["messages"].append("فشل: " + str(e))
    posts = []
    try:
        cc = wp_client()
        if cc:
            posts = cc.posts()
    except Exception:
        pass
    return render_template("wp.html", status=None, posts=posts,
                           ai_ok=bool(os.environ.get("AI_API_KEY")), result=result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
