"""생성 감시자 — 게시 계획(plans/*.json)이 제때 없으면 메일로 알린다.

맥이 닫혀 있으면 콘텐츠 생성이 안 되는데 맥 스스로는 알릴 수 없으므로,
GitHub Actions(클라우드)가 대신 확인한다.
- 밤 23:30 KST 체크: 내일 계획이 있어야 함 (21:00/22:33 생성 이후 시점)
- 아침 08:00 KST 체크: 오늘 계획이 있어야 함 (정오 게시 전 마지막 경고)
대상일 규칙: 실행 시각이 20시 이후면 내일, 아니면 오늘 (cron 지연에도 자동 보정)

환경변수: GMAIL_APP_PASSWORD, DISCORD_WEBHOOK, (테스트용) TEST_DATE
알림은 지메일 + 디스코드 이중 발송 — 한쪽이 실패해도 다른 쪽은 나간다.
"""
import json
import os
import smtplib
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

KST = timezone(timedelta(hours=9))
MAIL = "jinw0119@gmail.com"


def send_discord(text):
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not hook:
        print("DISCORD_WEBHOOK 없음 — 디스코드 생략")
        return
    try:
        req = urllib.request.Request(
            hook, data=json.dumps({"content": text}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
        print("디스코드 발송 완료")
    except Exception as e:
        print(f"디스코드 실패(메일은 별도 발송): {e}")


def main():
    now = datetime.now(KST)
    test_date = os.environ.get("TEST_DATE", "").strip()
    if test_date:
        target, label = test_date, "테스트"
    elif now.hour >= 20:
        target, label = (now.date() + timedelta(days=1)).isoformat(), "내일"
    else:
        target, label = now.date().isoformat(), "오늘"

    if os.path.exists(f"plans/{target}.json"):
        print(f"정상: plans/{target}.json 있음 ({label} 게시분 준비 완료)")
        return

    print(f"경고: plans/{target}.json 없음 — 알림 발송")
    body = (f"{label}({target}) 게시할 콘텐츠가 아직 생성되지 않았습니다.\n\n"
            f"원인: 맥이 닫혀 있거나 잠들어 있어 콘텐츠 생성이 실행되지 못했습니다.\n"
            f"조치: 맥북을 열고 전원을 연결해 주세요 — 여는 순간 자동으로 생성이 따라잡고,\n"
            f"게시 계획이 push되면 클라우드가 알아서 게시합니다.\n"
            f"(정오 게시 시간이 이미 지났다면, 다음 세션에서 수동 게시를 요청해 주세요)")
    send_discord(f"⚠️ **{label}({target}) 콘텐츠 미생성 — 맥북을 열어주세요**\n{body}")
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not pw:
        raise SystemExit("GMAIL_APP_PASSWORD 없음 — 메일 불가")
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = f"[얼마니 ⚠️] {label} 콘텐츠 미생성 — 맥북을 열어주세요"
    msg["From"] = msg["To"] = MAIL
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(MAIL, pw)
        s.send_message(msg)
    print("알림 메일 발송 완료")


if __name__ == "__main__":
    main()
