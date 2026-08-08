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

# 요일별 게시 시각(KST). weekday(): 월=0 … 일=6
# 2026-08-08 변경: cron 1일 1회로는 GitHub 스케줄 지연·누락에 무방비였다(그날 토요일 게시 실패).
# 이제 30분마다 실행하고, 이 표의 시각이 지났고 아직 done 마커가 없을 때만 게시한다.
POST_HOUR = {0: 12, 1: 19, 2: 12, 3: 19, 4: 12, 5: 11, 6: 20}


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


RECENT_HOURS = 6  # '방금 내 시도가 실제로는 성공했나'를 보는 창


def already_posted(uid, caption):
    """최근 RECENT_HOURS 안에 같은 캡션 첫 줄이 올라갔는지 — 2026-08-06 실증: 활동 제한
    403 응답이 와도 서버에선 게시가 완료되는 경우가 있어, 확인 없는 재시도는 중복이 된다.

    2026-08-08 수정: 예전엔 '최근 10개'로 봤는데, 그날 게시가 몇 건이었냐에 따라 판정이
    달라졌다(같은 날 오전엔 8/5 릴스를 잡아 막고, 오후엔 창 밖으로 밀려나 통과). 시간
    기준으로 바꿔 결정적으로 만든다. 며칠 전 같은 제목은 여기서 막을 일이 아니라
    소재 순환에서 걸러야 한다.
    """
    first = (caption or "").strip().split("\n")[0][:60]
    if not first:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)
    res = api(f"{uid}/media", {"fields": "caption,permalink,timestamp", "limit": 10})
    for m in res.get("data", []):
        if (m.get("caption") or "").strip().split("\n")[0][:60] != first:
            continue
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if ts >= cutoff:
            return m
    return None


def publish_with_backoff(uid, item):
    for i, delay in enumerate([0] + BACKOFF):
        if delay:
            print(f"활동 제한 — {delay//60}분 대기 후 재시도")
            time.sleep(delay)
        dup = already_posted(uid, item["caption"])
        if dup:  # 직전 '실패' 시도가 실제로는 게시됐던 경우 포함
            print(f"이미 게시됨 (중복 방지): {dup.get('permalink')}")
            return dup.get("id")
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


def window_open(now):
    """오늘의 게시 시각이 지났는가. 30분마다 도는 실행 중 '지금 올릴 차례'만 통과시킨다."""
    return now.hour >= POST_HOUR[now.weekday()]


def main():
    uid = os.environ["IG_USER_ID"]
    now = datetime.now(KST)
    today = now.date().isoformat()
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
    if not window_open(now):
        print(f"아직 게시 시각 전 (오늘 {POST_HOUR[now.weekday()]}시, 지금 {now:%H:%M}) — 종료")
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


def selftest():
    from datetime import date
    # 2026-08-08은 토요일 → 11시 창. 이날 10:59엔 안 열리고 11:00엔 열려야 한다.
    sat = date(2026, 8, 8)
    assert sat.weekday() == 5
    assert not window_open(datetime(2026, 8, 8, 10, 59, tzinfo=KST))
    assert window_open(datetime(2026, 8, 8, 11, 0, tzinfo=KST))
    assert window_open(datetime(2026, 8, 8, 23, 59, tzinfo=KST))
    # 일요일은 20시, 월요일은 12시
    assert not window_open(datetime(2026, 8, 9, 19, 30, tzinfo=KST))
    assert window_open(datetime(2026, 8, 9, 20, 1, tzinfo=KST))
    assert not window_open(datetime(2026, 8, 10, 11, 59, tzinfo=KST))
    assert window_open(datetime(2026, 8, 10, 12, 0, tzinfo=KST))
    assert set(POST_HOUR) == set(range(7)), "요일 7개 모두 정의되어야 함"
    print("publish_from_plan self-check ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
