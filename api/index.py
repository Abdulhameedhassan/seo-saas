import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, render_template

from audit_lib import crawl_site, find_conflicts, group_conflicts, intent_for, fix_for

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
    conflicts = find_conflicts(pages)
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
                           conflicts=conflicts, groups=groups, junk=junk)


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
