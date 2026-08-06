"""GitHub Actions에서 정시 실행 — plans/<KST날짜>.json 계획대로 인스타그램 게시.

로컬(맥)의 데일리 큐가 전날 밤 미디어 push + 계획 JSON 커밋을 해두면,
이 스크립트가 요일별 cron(publish.yml)으로 정시에 게시한다. 맥 불필요.

환경변수: IG_ACCESS_TOKEN, IG_USER_ID, (선택) GMAIL_APP_PASSWORD, DRY_RUN
"""
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

GRAPH = "https://graph.instagram.com/v21.0"
KST = timezone(timedelta(hours=9))
REEL_COMMENT = "풀버전은 프로필 피드 카드뉴스에 → @ur.money.kr 저장해두고 꺼내봐."
MAIL = "jinw0119@gmail.com"
SPACING = 300          # 게시물 간 간격 (연속 게시 시 활동 제한 — 2026-08-05/06 실증)
BACKOFF = [900, 1800]  # 2207051 활동 제한 백오프


def api(path, params=None, post=False):
    params = dict(params or {})
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    url = f"{GRAPH}/{path}"
    data = urllib.parse.urlencode(params).encode() if post else None
    if not post:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Graph API {e.code}: {body[:400]}") from None


def wait_container(cid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = api(cid, {"fields": "status_code"})["status_code"]
        if st == "FINISHED":
            return
        if st == "ERROR":
            raise RuntimeError(f"컨테이너 처리 실패: {cid}")
        time.sleep(15)
    raise RuntimeError(f"컨테이너 타임아웃: {cid}")


def publish_item(uid, item):
    if item["type"] == "reel":
        c = api(f"{uid}/media", {"media_type": "REELS", "video_url": item["media"][0],
                                 "caption": item["caption"]}, post=True)["id"]
    else:  # carousel
        children = []
        for url in item["media"]:
            children.append(api(f"{uid}/media", {"image_url": url,
                                                 "is_carousel_item": "true"}, post=True)["id"])
        for ch in children:
            wait_container(ch)
        c = api(f"{uid}/media", {"media_type": "CAROUSEL", "children": ",".join(children),
                                 "caption": item["caption"]}, post=True)["id"]
    wait_container(c)
    media_id = api(f"{uid}/media_publish", {"creation_id": c}, post=True)["id"]
    if item["type"] == "reel":
        api(f"{media_id}/comments", {"message": item.get("first_comment") or REEL_COMMENT}, post=True)
    return media_id


def publish_with_backoff(uid, item):
    for i, delay in enumerate([0] + BACKOFF):
        if delay:
            print(f"활동 제한 — {delay//60}분 대기 후 재시도")
            time.sleep(delay)
        try:
            return publish_item(uid, item)
        except RuntimeError as e:
            if "2207051" in str(e) and i < len(BACKOFF):
                continue
            raise


def notify(subject, body):
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not pw:
        print("GMAIL_APP_PASSWORD 없음 — 메일 생략")
        return
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, MAIL, MAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
            s.login(MAIL, pw)
            s.send_message(msg)
        print("알림 메일 발송")
    except Exception as e:  # 메일 실패는 게시 성공을 무효화하지 않는다
        print(f"메일 실패(무시): {e}")


def main():
    uid = os.environ["IG_USER_ID"]
    today = datetime.now(KST).date().isoformat()
    plan_path = f"plans/{today}.json"
    done_path = f"done/{today}"

    if os.environ.get("DRY_RUN", "false").lower() == "true":
        me = api("me", {"fields": "user_id,username"})
        print(f"DRY RUN — 토큰 유효 (@{me.get('username')})")
        if os.path.exists(plan_path):
            plan = json.load(open(plan_path))
            print(f"오늘 계획 {len(plan['items'])}건:")
            for it in plan["items"]:
                print(f"  - {it['type']}: {it['caption'][:30]!r} 미디어 {len(it['media'])}개")
        else:
            print(f"오늘 계획 없음: {plan_path} (테스트 시점엔 정상)")
        return

    if not os.path.exists(plan_path):
        print(f"계획 없음: {plan_path} — 종료 (맥에서 큐가 안 돌았거나 게시 없는 날)")
        return
    if os.path.exists(done_path):
        print(f"이미 게시됨: {done_path} — 종료")
        return
    plan = json.load(open(plan_path))

    lines = []
    for n, item in enumerate(plan["items"]):
        if n:
            time.sleep(SPACING)
        media_id = publish_with_backoff(uid, item)
        link = api(media_id, {"fields": "permalink"}).get("permalink", "")
        print(f"게시 완료 [{item['type']}] {link}")
        lines.append(f"{item['type']}: {link}")

    os.makedirs("done", exist_ok=True)
    open(done_path, "w").write(datetime.now(KST).isoformat() + "\n" + "\n".join(lines) + "\n")
    notify("[얼마니] 인스타 게시 완료 — 릴스 댓글 고정하러 가기", "\n".join(lines))


if __name__ == "__main__":
    main()
