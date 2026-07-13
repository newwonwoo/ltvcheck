/** guarantee 계산 테스트 — HUG 126% 룰 */
import {
  POLICY, limitFromPrice, maxDeposit, requiredPrice,
  ratioAtLeast, gradeOf, evaluateArea, parseMoney, formatMoney,
} from "./guarantee.js";

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log(`  ❌ ${m}`); } };

// ── 126% 룰 (공개 사례로 교차검증) ──
// 공시가 1.5억 → 주택가격 2.1억 → 한도 1.89억
ok(limitFromPrice(150_000_000) === 189_000_000, "공시가 1.5억 → 한도 1.89억");
ok(limitFromPrice(150_000_000) === Math.floor(150_000_000 * 1.26), "한도 = 공시가 × 126%");
ok(limitFromPrice(200_000_000) === 252_000_000, "공시가 2억 → 한도 2.52억");

// 선순위 5천만원이면 전세금 한도는 1.39억
ok(maxDeposit(150_000_000, 50_000_000) === 139_000_000, "선순위 5천 → 최대 전세금 1.39억");
ok(maxDeposit(150_000_000, 0) === 189_000_000, "선순위 0 → 최대 전세금 1.89억");
ok(maxDeposit(100_000_000, 200_000_000) === 0, "선순위가 한도 초과 → 0원 (음수 방지)");

// 역산: 전세금 2억 + 선순위 0 → 필요 공시가
ok(requiredPrice(200_000_000, 0) === Math.ceil(200_000_000 / 1.26), "전세 2억 → 필요 공시가");
ok(requiredPrice(200_000_000, 0) === 158_730_159, "전세 2억 → 공시가 1.587억 필요");
ok(requiredPrice(200_000_000, 50_000_000) > requiredPrice(200_000_000, 0), "선순위 있으면 필요 공시가 상승");
ok(requiredPrice(0, 0) === 0, "전세금 0 → 0");

// 왕복 검증
const p = 180_000_000, s = 30_000_000;
const md = maxDeposit(p, s);
ok(requiredPrice(md, s) <= p + 1, "왕복: 최대전세금으로 역산하면 원래 공시가 이하");

// ── 히스토그램 비율 ──
const BIN = 10_000_000;
// 100건: 0~1억 20건, 1~2억 50건, 2~3억 30건
const hist = Array(51).fill(0);
for (let i = 0; i < 10; i++) hist[i] = 2;   // 0~1억 : 20건
for (let i = 10; i < 20; i++) hist[i] = 5;  // 1~2억 : 50건
for (let i = 20; i < 30; i++) hist[i] = 3;  // 2~3억 : 30건

ok(Math.abs(ratioAtLeast(hist, 0, BIN) - 1) < 0.01, "임계 0 → 100%");
ok(Math.abs(ratioAtLeast(hist, 100_000_000, BIN) - 0.8) < 0.01, "1억 이상 → 80%");
ok(Math.abs(ratioAtLeast(hist, 200_000_000, BIN) - 0.3) < 0.01, "2억 이상 → 30%");
ok(ratioAtLeast(hist, 500_000_000, BIN) === 0, "5억 이상 → 0%");
ok(ratioAtLeast([], 100, BIN) === null, "빈 히스토그램 → null");

// 구간 중간 보간: 1.5억 이상 → 1~2억 구간 절반(25) + 2억이상(30) = 55%
ok(Math.abs(ratioAtLeast(hist, 150_000_000, BIN) - 0.55) < 0.02, "구간 중간 보간");

// ── 등급 ──
ok(gradeOf(0.9).key === "GOOD", "90% → 가능성 높음");
ok(gradeOf(0.7).key === "GOOD", "70% → 가능성 높음(경계)");
ok(gradeOf(0.5).key === "MID", "50% → 애매");
ok(gradeOf(0.3).key === "MID", "30% → 애매(경계)");
ok(gradeOf(0.1).key === "HARD", "10% → 살짝 힘듦");
ok(gradeOf(null) === null, "비율 없으면 등급 없음");

// ── 동네 평가 ──
const area = { dong: "구로동", count: 100, avg: 150_000_000, median: 145_000_000, hist };
const ev = evaluateArea(area, 200_000_000, 0, BIN);
ok(ev.need === requiredPrice(200_000_000, 0), "필요 공시가 계산");
ok(ev.grade != null, "등급 부여");
ok(ev.avgMaxDeposit === maxDeposit(150_000_000, 0), "평균 공시가 기준 최대 전세금");

// 선순위가 커지면 등급이 나빠져야
const ev2 = evaluateArea(area, 200_000_000, 80_000_000, BIN);
ok(ev2.ratio < ev.ratio, "선순위 증가 → 충족 비율 하락");

// ── 금액 입력 파싱 ──
ok(parseMoney("180000000") === 180_000_000, "숫자 그대로");
ok(parseMoney("1억 8천") === 180_000_000, "1억 8천");
ok(parseMoney("2억") === 200_000_000, "2억");
ok(parseMoney("1억8000만원") === 180_000_000, "1억8000만원");
ok(parseMoney("18,000만원") === 180_000_000, "18,000만원");
ok(parseMoney("5천") === 50_000_000, "5천 = 5천만원");
ok(parseMoney("") === null, "빈값 → null");
ok(parseMoney("abc") === null, "문자 → null");

ok(formatMoney(180_000_000) === "1억 8,000만원", "표기: 1억 8,000만원");
ok(formatMoney(0) === "0원", "표기: 0원");

console.log(`\n${fail === 0 ? "✅" : "❌"} guarantee: ${pass} 통과, ${fail} 실패`);
process.exit(fail === 0 ? 0 : 1);
