/**
 * guarantee.js — 공시가 기준 보증한도 계산
 *
 * HUG 전세보증금반환보증 (비아파트 = 연립·다세대)
 *   주택가격 = 공시가격 × 140%           (1순위 가격 산정)
 *   보증한도 = 주택가격 × 90%            (담보인정비율)
 *            = 공시가격 × 126%           ('126% 룰', 2023.5 시행)
 *   조건: 선순위채권 + 전세보증금 ≤ 공시가격 × 126%
 *
 * ※ 2026년 7월 현재 126% 유효. 담보인정비율 80%(=112%) 하향은 검토만 되고 미시행.
 * ※ 정책이 바뀌면 POLICY 한 곳만 고치면 된다. 코드 곳곳에 숫자를 박지 않는다.
 * ※ 아파트는 시세(KB 등)를 우선 쓰므로 이 계산이 성립하지 않는다 → 대상 제외.
 * ※ 오피스텔은 공시가격이 아니라 국세청 기준시가 기준이라 별도 확인 필요.
 */

export const POLICY = {
  version: "2023-05",
  label: "공시가 126% 룰",
  priceRate: 1.4,   // 주택가격 = 공시가 × 140%
  ltv: 0.9,         // 담보인정비율 90%
  targets: ["연립", "다세대"],
};

/** 공시가 → 보증한도 (선순위·전세금 합계 상한) */
export function limitFromPrice(price, policy = POLICY) {
  if (!price || price <= 0) return 0;
  return Math.floor(price * policy.priceRate * policy.ltv);
}

/** 공시가 + 선순위채권 → 가능한 최대 전세금 */
export function maxDeposit(price, seniorClaim = 0, policy = POLICY) {
  return Math.max(0, limitFromPrice(price, policy) - (seniorClaim || 0));
}

/** 전세금 + 선순위채권 → 필요한 최소 공시가 */
export function requiredPrice(deposit, seniorClaim = 0, policy = POLICY) {
  if (!deposit || deposit <= 0) return 0;
  return Math.ceil((deposit + (seniorClaim || 0)) / (policy.priceRate * policy.ltv));
}

/**
 * 히스토그램에서 임계값 이상인 비율
 * hist: 구간별 건수 배열. i번째 = [i*binSize, (i+1)*binSize). 마지막 칸은 binMax 초과.
 * 임계값이 구간 중간에 걸리면 선형 보간한다.
 */
export function ratioAtLeast(hist, threshold, binSize, binMax) {
  if (!hist || !hist.length) return null;
  const total = hist.reduce((s, n) => s + n, 0);
  if (!total) return null;

  let above = 0;
  for (let i = 0; i < hist.length; i++) {
    const n = hist[i];
    if (!n) continue;
    const lo = i * binSize;
    const hi = i === hist.length - 1 ? Infinity : lo + binSize;
    if (lo >= threshold) {
      above += n;
    } else if (hi > threshold) {
      // 구간 내에 임계값이 걸림 → 균등분포 가정 보간
      const span = hi === Infinity ? binSize : hi - lo;
      above += n * ((hi === Infinity ? lo + binSize : hi) - threshold) / span;
    }
  }
  return Math.min(1, Math.max(0, above / total));
}

/** 충족 비율 → 등급 */
export const GRADES = {
  GOOD: { key: "GOOD", label: "가능성 높음", icon: "🟢", min: 0.7 },
  MID: { key: "MID", label: "애매함", icon: "🟡", min: 0.3 },
  HARD: { key: "HARD", label: "살짝 힘듦", icon: "🔴", min: 0 },
};

export function gradeOf(ratio) {
  if (ratio == null) return null;
  if (ratio >= GRADES.GOOD.min) return GRADES.GOOD;
  if (ratio >= GRADES.MID.min) return GRADES.MID;
  return GRADES.HARD;
}

/**
 * 동네 하나를 평가한다.
 * area: {dong, count, avg, median, hist, ...}
 */
export function evaluateArea(area, deposit, seniorClaim, binSize, binMax, policy = POLICY) {
  const need = requiredPrice(deposit, seniorClaim, policy);
  const ratio = ratioAtLeast(area.hist, need, binSize, binMax);
  return {
    ...area,
    need,
    ratio,
    grade: gradeOf(ratio),
    // 이 동네 '평균' 공시가라면 전세금을 얼마까지 넣을 수 있나
    avgMaxDeposit: maxDeposit(area.avg, seniorClaim, policy),
    medianMaxDeposit: maxDeposit(area.median, seniorClaim, policy),
  };
}

/** 금액 문자열 → 정수 ("1억 8천", "180000000", "18,000만원") */
export function parseMoney(input) {
  if (input == null) return null;
  const s = String(input).replace(/[\s,]/g, "");
  if (!s) return null;
  if (/^\d+$/.test(s)) return parseInt(s, 10);

  let total = 0;
  let matched = false;
  const eok = s.match(/(\d+(?:\.\d+)?)억/);
  if (eok) { total += parseFloat(eok[1]) * 100_000_000; matched = true; }
  const man = s.match(/(\d+(?:\.\d+)?)(?:천만|만)/);
  if (man) {
    const unit = s.includes("천만") ? 10_000_000 : 10_000;
    total += parseFloat(man[1]) * unit;
    matched = true;
  } else {
    const chun = s.match(/(\d+(?:\.\d+)?)천(?!만)/);
    if (chun) { total += parseFloat(chun[1]) * 10_000_000; matched = true; }
  }
  return matched ? Math.round(total) : null;
}

/** 정수 → "1억 8,000만원" 같은 읽기 쉬운 표기 */
export function formatMoney(n) {
  if (n == null) return "-";
  if (n === 0) return "0원";
  const eok = Math.floor(n / 100_000_000);
  const man = Math.floor((n % 100_000_000) / 10_000);
  const parts = [];
  if (eok) parts.push(`${eok}억`);
  if (man) parts.push(`${man.toLocaleString()}만`);
  return parts.length ? parts.join(" ") + "원" : `${n.toLocaleString()}원`;
}
