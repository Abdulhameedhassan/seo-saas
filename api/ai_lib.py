import os

import requests


class AIError(Exception):
    pass


SYS = "أنت خبير SEO ومحرر عربي. أعد المطلوب فقط بدون شرح أو مقدمات."


def chat(user_prompt, max_tokens=2000, temperature=0.7):
    key = os.environ.get("AI_API_KEY", "")
    if not key:
        raise AIError("AI_API_KEY غير مضبوط في متغيرات البيئة")
    base = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("AI_MODEL", "")
    if not model:
        model = "gemini-2.0-flash" if "generativelanguage" in base else "gpt-4o-mini"
    try:
        r = requests.post(base + "/chat/completions",
                          headers={"Authorization": "Bearer " + key},
                          json={"model": model,
                                "messages": [{"role": "system", "content": SYS},
                                             {"role": "user", "content": user_prompt}],
                                "temperature": temperature, "max_tokens": max_tokens},
                          timeout=60)
    except requests.RequestException as e:
        raise AIError("AI request failed: " + str(e))
    if r.status_code != 200:
        raise AIError("AI HTTP " + str(r.status_code) + " " + r.text[:200])
    try:
        return r.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise AIError("AI bad response")


def seo_title(kw, old):
    return chat("الكلمة المستهدفة: %s\nالعنوان الحالي: %s\n"
                "اكتب SEO title عربي لا يزيد عن 60 حرفا يبدأ بالكلمة المستهدفة ومعه ميزة واحدة "
                "(معتمد/سريع/للسفارات) واسم جالينوس في الآخر. أعد العنوان فقط." % (kw, old),
                max_tokens=200)


def meta_desc(kw):
    return chat("الكلمة: %s\nاكتب Meta Description عربية حوالي 150 حرفا فيها فائدة "
                "ودعوة لواتساب وتقييم مجاني. أعد الوصف فقط." % kw, max_tokens=300)


def rewrite_article(kw, content):
    return chat("أعد كتابة المقال التالي بأسلوب SEO عربي: عنوان H1 بالكلمة %s، عناوين H2، "
                "فقرات قصيرة، وقسم أسئلة شائعة من 4 أسئلة. "
                "أعد HTML فقط (h1/h2/p/ul/li) بدون head أو body.\n\nالمحتوى الحالي:\n%s"
                % (kw, content[:3000]), max_tokens=4000)


def new_article(kw, intent):
    return chat("اكتب مقال SEO عربي كامل يستهدف الكلمة: %s (النية: %s). الهيكل: H1 بالكلمة، "
                "مقدمة فيها الكلمة، 4 عناوين H2، أسئلة شائعة 4 أسئلة، ودعوة واتساب لجالينوس. "
                "أعد HTML فقط." % (kw, intent), max_tokens=4000)
