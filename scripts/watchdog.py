"""생성 감시자 — 게시 계획(plans/*.json)이 제때 없으면 메일로 알린다.

맥이 닫혀 있으면 콘텐츠 생성이 안 되는데 맥 스스로는 알릴 수 없으므로,
GitHub Actions(클라우드)가 대신 확인한다.
- 밤 23:35 KST 체크: 내일 계획이 있어야 함 (21:00/22:33 생성 이후 시점)
- 아침 08:05 KST 체크: 오늘 계획이 있어야 함 (11시 게시 전 마지막 경고)
- 낮 12:35 KST 체크: 오늘 게시가 실제로 됐는지 (실패를 그날 안에 알아야 손을 쓴다)
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
            # Discord는 기본 python-urllib UA를 차단(403) — UA 명시 필수
            headers={"Content-Type": "application/json",
                     "User-Agent": "urmoney-watchdog/1.0 (+https://github.com/jinw0119/urmoney-media)"})
        urllib.request.urlopen(req, timeout=20)
        print("디스코드 발송 완료")
    except Exception as e:
        print(f"디스코드 실패(메일은 별도 발송): {e}")


def send_mail(subject, body):
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not pw:
        raise SystemExit("GMAIL_APP_PASSWORD 없음 — 메일 불가")
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = msg["To"] = MAIL
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(MAIL, pw)
        s.send_message(msg)
    print("알림 메일 발송 완료")


def check_published(now):
    """밤 실행에서 오늘 게시가 실제로 됐는지 확인 — 계획은 있는데 done 마커가 없으면 누락.

    2026-08-08: 토요일 크론이 아예 안 떠서 게시가 조용히 빠졌는데 아무 알림도 없었다.
    감시자가 '생성'만 보고 '게시'는 안 봤던 탓 — 이 확인을 추가한다.
    """
    today = now.date().isoformat()
    if not os.path.exists(f"plans/{today}.json") or os.path.exists(f"done/{today}"):
        return
    print(f"경고: plans/{today}.json은 있는데 done/{today}이 없음 — 게시 누락 알림")
    body = (f"오늘({today}) 게시 계획은 있는데 게시 완료 기록이 없습니다.\n\n"
            f"게시 워크플로가 실패했거나, 토큰 만료·활동 제한일 수 있습니다.\n"
            f"확인: https://github.com/jinw0119/urmoney-media/actions")
    send_discord(f"⚠️ **오늘({today}) 게시 누락 의심**\n{body}")
    send_mail("[얼마니 ⚠️] 오늘 게시가 안 된 것 같습니다", body)


def main():
    now = datetime.now(KST)
    test_date = os.environ.get("TEST_DATE", "").strip()
    # 게시 시각(post_hour 11)이 지난 뒤부터 게시 완료를 따진다.
    # 21시 이후로 잡아뒀더니 실패를 12시간 뒤에 알게 돼 그날 손쓸 수가 없었다.
    if not test_date and now.hour >= 12:
        check_published(now)
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
    # 2026-08-30: 예전엔 원인을 "맥이 닫혀서"로 단정했는데, 이 watchdog는 클라우드(GH Actions)라
    # 맥 상태를 알 수 없다. 계획이 없는 이유는 여러 가지(야간 큐 미실행·렌더 절전 중단·세션 hang·
    # 소재 미정·에러)다. 사실(계획 없음)만 쓰고 원인은 후보로만 나열한다.
    body = (f"{label}({target}) 게시 계획(plans/{target}.json)이 아직 없습니다.\n\n"
            f"확인 필요: 야간 큐가 계획을 push하지 못했습니다.\n"
            f"가능한 원인 — 큐 세션 미실행 / 렌더 중 맥 절전으로 중단 / 세션 hang / 소재 미정 / 에러.\n"
            f"(원인을 단정하지 않습니다. 맥이 켜져 있어도 렌더가 절전에 막히면 발생할 수 있습니다.)\n\n"
            f"조치: 맥이 깨어 있는지 확인하고, 큐 세션이 멈춰 있으면 정리 후 재실행하거나\n"
            f"수동으로 콘텐츠를 만들어 계획을 push해 주세요.\n"
            f"(11시 게시 시각이 이미 지났다면 다음 세션에서 수동 게시를 요청해 주세요)")
    send_discord(f"⚠️ **{label}({target}) 게시 계획 없음 — 확인 필요**\n{body}")
    send_mail(f"[얼마니 ⚠️] {label} 게시 계획 없음 — 확인 필요", body)


if __name__ == "__main__":
    main()
