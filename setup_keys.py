#!/usr/bin/env python3
"""
setup_keys.py — API 키 입력 → .env.local 자동 저장 (엔벨롭)

실행:  python3 setup_keys.py

하는 일:
  1) 필요한 키를 하나씩 물어본다.
  2) 입력한 값을 .env.local 에 저장한다(이 파일은 .gitignore로 보호되어 깃에 안 올라감).
  3) 이미 있던 값은 그대로 두고, 새로 입력한 것만 덮어쓴다(엔터만 누르면 유지).

즉 "키 입력하면 자동으로 안전하게 저장"되는 구조.
운영(Vercel)에서는 같은 키들을 대시보드 Environment Variables 에 등록하면 됨.
"""

import os

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")

# (환경변수명, 설명, 발급처)
KEYS = [
    ("JUSO_API_KEY",  "행안부 주소검색 API 키 (도로명/지번→PNU)", "business.juso.go.kr"),
    ("VWORLD_API_KEY", "VWorld 인증키 (공동주택 공시가격 조회)", "www.vworld.kr"),
    ("VWORLD_DOMAIN", "VWorld 키 발급 시 등록한 도메인", "예: localhost 또는 vercel 주소"),
    ("OFFICETEL_DB_PATH", "오피스텔 기준시가 SQLite 경로", "build_officetel_db.py로 생성"),
]


def _load_existing():
    """기존 .env.local 을 읽어 dict로."""
    vals = {}
    if not os.path.exists(ENV_FILE):
        return vals
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def _mask(v):
    if not v:
        return "(비어있음)"
    return v[:3] + "•" * max(0, len(v) - 6) + v[-3:] if len(v) > 6 else "•" * len(v)


def main():
    print("\n=== jeonse-pnu API 키 설정 ===")
    print("값을 입력하면 .env.local 에 안전하게 저장됩니다.")
    print("(엔터만 누르면 기존 값 유지)\n")

    existing = _load_existing()
    result = dict(existing)

    for name, desc, where in KEYS:
        cur = existing.get(name, "")
        prompt = f"• {desc}\n  [{where}] 현재값 {_mask(cur)}\n  새 키 입력> "
        entered = input(prompt).strip()
        if entered:
            result[name] = entered
        print()

    # .env.local 작성 (키=값, 주석 헤더 포함)
    lines = [
        "# jeonse-pnu 로컬 키 (자동 생성 · 절대 깃에 커밋 금지)",
        "# 이 파일은 .gitignore로 보호됩니다.",
        "",
    ]
    for name, _, _ in KEYS:
        lines.append(f"{name}={result.get(name, '')}")
    # 사용자가 추가했던 기타 키도 보존
    for k, v in result.items():
        if k not in {n for n, _, _ in KEYS}:
            lines.append(f"{k}={v}")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # 안전 권한(읽기/쓰기 본인만) — OS가 지원하면
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass

    filled = sum(1 for n, _, _ in KEYS if result.get(n))
    print(f"저장 완료 → {ENV_FILE}")
    print(f"설정된 키: {filled}/{len(KEYS)}")
    if filled < len(KEYS):
        print("※ 비어있는 키가 있으면 해당 단계는 동작하지 않습니다.")
    print("운영(Vercel): 같은 키들을 대시보드 Environment Variables 에 등록하세요.\n")


if __name__ == "__main__":
    main()
