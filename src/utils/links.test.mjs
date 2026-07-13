/** 네이버 center 인코딩 검증 — 실기기로 확인된 값 기준 */
import { naverCenter, readNaverCenter, naverLandUrl } from "./links.js";

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log(`  ❌ ${m}`); } };

// 네이버가 실제로 만든 center (사용자 폰에서 캡처)
const REAL = "3zfQf6-2AHIg8";
const got = readNaverCenter(REAL);
ok(Math.abs(got.lat - 37.4632) < 1e-6, "네이버 center 디코딩 (위도)");
ok(Math.abs(got.lon - 126.9346) < 1e-6, "네이버 center 디코딩 (경도)");
ok(naverCenter(got.lat, got.lon) === REAL, "재인코딩 → 원본과 완전 일치");

// 왕복
for (const [lat, lon] of [[37.5085, 126.8894], [35.152, 126.848], [33.4996, 126.5312]]) {
  const c = naverCenter(lat, lon);
  const b = readNaverCenter(c);
  ok(Math.abs(b.lat - lat) < 1e-6 && Math.abs(b.lon - lon) < 1e-6, `왕복 (${lat}, ${lon})`);
  ok(c.length === 13 && c.includes("-"), `형식 6자-6자 (${lat})`);
}

// 실기기에서 정확히 맞은 케이스: 광주 치평동
ok(naverCenter(35.152, 126.848) === "3zccXm-2z8JLW", "광주 치평동 center (실기기 확인)");

// URL 생성
const url = naverLandUrl(200000000, { lat: 37.5085, lon: 126.8894 });
ok(url.includes("tradeTypes=B1"), "전세 필터");
ok(url.includes("warrantyPrice=0-200000000"), "보증금 상한");
ok(url.includes("center="), "좌표 포함");
ok(!naverLandUrl(200000000).includes("center="), "좌표 없으면 center 생략");

console.log(`\n${fail === 0 ? "✅" : "❌"} links: ${pass} 통과, ${fail} 실패`);
process.exit(fail === 0 ? 0 : 1);
