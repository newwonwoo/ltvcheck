"""
confidence.py — 신뢰도 점수 계산

정제는 '됐다/안 됐다'의 흑백이 아니라 '얼마나 믿을 만한가'의 문제예요.
- 주소가 1차 엔진(juso)에서 정확히 잡혔나, 폴백까지 갔나
- 호까지 떨어졌나, 동만 잡혔나
- 등기번호로 교차검증이 됐나

이런 신호를 모아 0~100 점수와 등급(A/B/C/F)을 매겨서,
점수가 낮으면 화면에서 "수동 확인 필요"를 띄우게 합니다.
공모에서도 "우리는 불확실성을 숨기지 않고 표시한다"는 어필 포인트가 돼요.
"""

from dataclasses import dataclass, field


# 각 신호별 배점.
# 주의: '1차'와 '폴백'은 배타적(둘 중 하나만 켜짐)이라, 둘을 합산하지 않는다.
# 1차 성공 경로의 최대점이 정확히 100이 되도록 설계:
#   1차(40) + 지번(15) + 호(28) + 교차검증(17) = 100  -> A등급
# 폴백 경로는 1차보다 불확실하므로 최대 82점(B등급 상한)에 머물게:
#   폴백(22) + 지번(15) + 호(28) + 교차검증(17) = 82  -> B등급
WEIGHTS = {
    "주소_정제_1차": 40,    # juso 1차에서 PNU 4요소 확보
    "주소_정제_폴백": 22,    # 카카오/VWorld 폴백으로 확보(1차 실패)
    "지번_확인": 15,        # 본번/부번이 명확
    "호_확인": 28,          # 전유부분(호)까지 확정
    "등기_교차검증": 17,     # 등기고유번호로 추가 확인됨
}


@dataclass
class Confidence:
    score: int = 0
    grade: str = "F"
    signals: dict = field(default_factory=dict)  # 어떤 신호가 켜졌는지
    notes: list = field(default_factory=list)

    @property
    def needs_manual_check(self):
        # B등급 미만이면 사람이 한 번 확인하는 게 안전
        return self.grade in ("C", "F")


def _grade(score):
    if score >= 85:
        return "A"
    if score >= 65:
        return "B"
    if score >= 40:
        return "C"
    return "F"


def score_confidence(*, refine_tier=None, has_jibun=False, has_ho=False,
                     registry_cross_checked=False, warnings=None):
    """
    신뢰도를 계산한다.

    refine_tier: 1=juso 1차 성공, 2=폴백 성공, None/0=실패
    has_jibun:   본번/부번 확보 여부
    has_ho:      호 확정 여부
    registry_cross_checked: 등기번호로 교차검증됨
    warnings:    파서/엔진이 남긴 경고 리스트
    """
    c = Confidence()
    total = 0

    if refine_tier == 1:
        total += WEIGHTS["주소_정제_1차"]
        c.signals["주소_정제_1차"] = True
    elif refine_tier == 2:
        total += WEIGHTS["주소_정제_폴백"]
        c.signals["주소_정제_폴백"] = True
        c.notes.append("1차 정제 실패 → 폴백 엔진으로 확보")

    if has_jibun:
        total += WEIGHTS["지번_확인"]
        c.signals["지번_확인"] = True
    if has_ho:
        total += WEIGHTS["호_확인"]
        c.signals["호_확인"] = True
    else:
        c.notes.append("호 미확정 → 단지/동 단위까지만 식별됨")
    if registry_cross_checked:
        total += WEIGHTS["등기_교차검증"]
        c.signals["등기_교차검증"] = True

    for w in (warnings or []):
        c.notes.append(w)
        total -= 3  # 경고 하나당 소폭 감점

    total = max(0, min(100, total))
    c.score = total
    c.grade = _grade(total)
    return c
