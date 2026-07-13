/**
 * registryParser 테스트 — 실제 등기부 PDF 2건(좌표 아이템)으로 검증
 * 실행: node src/utils/registryParser.test.mjs
 */
import { parseRegistryItems, validateItems, parseAmount, restoreTable, parseSummary } from "./registryParser.js";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dir = dirname(fileURLToPath(import.meta.url));
const load = (f) => JSON.parse(readFileSync(join(__dir, "__fixtures__", f), "utf-8"));

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log(`  ❌ ${m}`); } };

// ── 게이트 ──
ok(!validateItems([]).ok, "빈 아이템 거부");
ok(!validateItems([{page:0,x:0,y:0,text:"안녕"}]).ok, "짧은 텍스트 거부(스캔본)");
ok(parseAmount("10,000,000") === 10000000, "금액 파싱");

// ── 케이스 1: 을구 없음, 압류·가처분 전부 말소 → CLEAN ──
const r1 = parseRegistryItems(load("registry_no_eul.json"));
ok(r1.ok, "케이스1 파싱");
ok(r1.property.uniqueNo === "1146-1996-129797", "고유번호");
ok(r1.owner?.name === "이재임", "현재 소유자");
ok(r1.owner?.isTrust === false, "신탁 아님");
ok(r1.seniorClaim.activeMaxClaimTotal === 0, "근저당 없음 → 0원");
ok(r1.riskFlags.length === 0, "유효 위험 없음(전부 말소)");
ok(r1.cancelledFlags.length === 3, "말소 3건(3·5번 압류, 6번 가처분)");
ok(r1.riskLevel === "CLEAN", "CLEAN");
// 가처분 금지사항의 '임차권' 오탐 없어야
ok(!r1.riskFlags.some(f => f.kind.includes("임차권")), "임차권 오탐 없음");

// ── 케이스 2: 근저당 + 신탁 + 복수말소 (어려운 케이스) ──
const r2 = parseRegistryItems(load("registry_mortgage.json"));
ok(r2.ok, "케이스2 파싱");
ok(r2.property.uniqueNo === "1201-2018-048485", "고유번호2");

// ★ 근저당: 3번 1천만원 유효
ok(r2.seniorClaim.activeMaxClaimTotal === 10000000, "유효 채권최고액 1,000만원");
ok(r2.seniorClaim.mortgages.length === 1, "유효 근저당 1건");
ok(r2.seniorClaim.mortgages[0].rank === 3, "근저당 순위 3번");
ok(r2.seniorClaim.mortgages[0].creditor === "송림중앙신용협동조합", "근저당권자");

// ★ 복수 말소: 14번 "10번가압류, 11번압류, 12번강제경매개시결정등기말소"
const cancelledRanks = r2.cancelledFlags.filter(f => f.section === "갑구").map(f => f.rank);
ok(cancelledRanks.includes(10), "10번 가압류 말소");
ok(cancelledRanks.includes(11), "11번 압류 말소");
ok(cancelledRanks.includes(12), "12번 강제경매 말소");
ok(!r2.riskFlags.some(f => f.rank === 12), "강제경매 유효위험 아님(말소됨)");
ok(!r2.riskFlags.some(f => f.rank === 14), "14번(말소이벤트 행)은 위험 아님");

// ★ 신탁: 15번 유효, 2·5번 말소
ok(r2.owner?.isTrust === true, "현재 신탁 상태");
ok(r2.owner?.name === "대한토지신탁주식회사", "수탁자명");
ok(r2.riskFlags.some(f => f.rank === 15 && f.kind === "신탁"), "15번 신탁 유효 위험");
ok(r2.cancelledFlags.some(f => f.rank === 2 && f.kind === "신탁"), "2번 신탁 말소");

// ★ 을구 3-1 '공동담보소멸'을 근저당 말소로 오판하면 안 됨
ok(!r2.seniorClaim.mortgages[0].cancelled, "3번 근저당 유효 (3-1 공동담보소멸은 말소 아님)");

// ★ 을구 1번 주택임차권 말소
ok(r2.cancelledFlags.some(f => f.section === "을구" && f.rank === 1), "을구 1번 임차권 말소");

ok(r2.riskLevel === "HAS_RIGHTS", "종합 HAS_RIGHTS");

// ── 표 복원 자체 검증 ──
const rows = restoreTable(load("registry_mortgage.json"));
const r14 = rows.find(r => r.section === "갑구" && r.rank === 14);
ok(r14 && r14.purpose.replace(/\s/g,"").includes("12번강제경매개시결정등기말소"),
   "14번 등기목적 인터리브 복원");
ok(!rows.some(r => r.section === "표제부"), "표제부 행 제외");

// ── 주요 등기사항 요약 페이지 파싱 ──
const sum2 = parseSummary(load("registry_mortgage.json"));
ok(sum2.present === true, "요약 페이지 감지(계산동)");

// §1 소유지분현황
ok(sum2.owners.length === 1, "요약 §1 소유자 1명");
ok(sum2.owners[0].name.includes("대한토지신탁주식회사"), "요약 §1 소유자명 (두 줄 이름 복원)");
ok(sum2.owners[0].name.includes("수탁자"), "요약 §1 수탁자 표기");
ok(sum2.owners[0].share === "단독소유", "요약 §1 최종지분");
ok(sum2.owners[0].rank === "15", "요약 §1 순위번호");

// §2 소유권 제한사항
ok(sum2.rights.length === 1, "요약 §2 제한사항 1건");
ok(sum2.rights[0].rank === "15-1", "요약 §2 부기 순위(15-1)");
ok(sum2.rights[0].purpose.includes("약정"), "요약 §2 등기목적");

// §3 (근)저당권·전세권
ok(sum2.mortgages.length === 1, "요약 §3 근저당 1건");
ok(sum2.mortgages[0].rank === "3", "요약 §3 순위 3번");
ok(sum2.mortgages[0].amount === 10000000, "요약 §3 채권최고액 1,000만원");
ok(sum2.mortgages[0].creditor === "송림중앙신용협동조합", "요약 §3 근저당권자");
ok(sum2.mortgageTotal === 10000000, "요약 채권최고액 합계");

// 말소된 권리는 요약에 없어야 함 (요약은 말소되지 않은 사항만)
ok(!sum2.rights.some((r) => /압류|경매/.test(r.purpose)), "요약에 말소된 압류·경매 없음");
ok(!sum2.mortgages.some((m) => /임차권/.test(m.purpose)), "요약에 말소된 임차권 없음");

// 요약 없는 발급본
const sum1 = parseSummary(load("registry_no_eul.json"));
ok(sum1.present === false, "요약 페이지 없음(상록수)");
ok(sum1.mortgages.length === 0, "요약 없으면 근저당 0건");

// ── 교차검증 (본문 파싱 vs 요약) ──
ok(r2.crossCheck.available === true, "교차검증 가능(요약 있음)");
ok(r2.crossCheck.mortgageMatch === true, "채권최고액: 본문 == 요약");
ok(r2.crossCheck.ownerMatch === true, "소유자: 본문 == 요약");
ok(r2.crossCheck.ok === true, "교차검증 통과");
ok(r2.crossCheck.summaryMortgageTotal === r2.seniorClaim.activeMaxClaimTotal,
   "요약 금액 == 본문 유효 채권최고액");

ok(r1.crossCheck.available === false, "요약 없으면 교차검증 불가 표시");

console.log(`\n${fail === 0 ? "✅" : "❌"} registryParser: ${pass} 통과, ${fail} 실패`);
process.exit(fail === 0 ? 0 : 1);
