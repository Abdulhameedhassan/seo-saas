import requests
from requests.auth import HTTPBasicAuth


class WPError(Exception):
    pass


class WPClient:
    def __init__(self, base, user, password):
        self.base = base.rstrip("/")
        self.auth = HTTPBasicAuth(user, password)

    def _url(self, path):
        return self.base + "/wp-json/wp/v2" + path

    def check(self):
        r = requests.get(self._url("/"), auth=self.auth, timeout=15)
        if r.status_code in (200, 201):
            return True, r.json().get("name", "WordPress")
        return False, "HTTP " + str(r.status_code)

    def posts(self, per_page=10, search=""):
        params = {"per_page": per_page, "orderby": "modified",
                  "_fields": "id,title,link,status,modified"}
        if search:
            params["search"] = search
        r = requests.get(self._url("/posts"), auth=self.auth, params=params, timeout=20)
        if r.status_code != 200:
            raise WPError("posts list failed: HTTP " + str(r.status_code))
        out = []
        for p in r.json():
            out.append({"id": p["id"], "title": (p.get("title") or {}).get("rendered", ""),
                        "link": p.get("link", ""), "status": p.get("status", "")})
        return out

    def get_post(self, pid):
        r = requests.get(self._url("/posts/%s" % pid), auth=self.auth,
                         params={"context": "edit",
                                 "_fields": "id,title,content,excerpt,link,status,slug"},
                         timeout=20)
        if r.status_code != 200:
            raise WPError("get post failed: HTTP " + str(r.status_code))
        p = r.json()
        return {"id": p["id"], "title": p["title"].get("raw", ""),
                "content": p["content"].get("raw", ""), "excerpt": p["excerpt"].get("raw", ""),
                "link": p.get("link", ""), "status": p.get("status", "")}

    def update_post(self, pid, data):
        r = requests.post(self._url("/posts/%s" % pid), auth=self.auth, json=data, timeout=30)
        if r.status_code not in (200, 201):
            raise WPError("update failed: HTTP " + str(r.status_code) + " " + r.text[:200])
        return r.json().get("link", "")

    def try_meta(self, pid, key, value):
        try:
            r = requests.post(self._url("/posts/%s" % pid), auth=self.auth,
                              json={"meta": {key: value}}, timeout=20)
            return r.status_code in (200, 201)
        except requests.RequestException:
            return False

    def create_post(self, title, content, status="draft"):
        r = requests.post(self._url("/posts"), auth=self.auth,
                          json={"title": title, "content": content, "status": status}, timeout=30)
        if r.status_code not in (200, 201):
            raise WPError("create failed: HTTP " + str(r.status_code) + " " + r.text[:200])
        j = r.json()
        return j.get("id"), j.get("link", "")
