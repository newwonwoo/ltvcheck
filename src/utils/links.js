/**
 * links.js — 외부 서비스 링크
 *
 * 네이버페이 부동산 (fin.land.naver.com) — 실기기로 검증한 파라미터
 *   tradeTypes=B1                                  전세
 *   realEstateTypes=A05-A06-A07-C02-C03-C01-A02    오피스텔·빌라·원룸·단독다가구 (아파트 제외)
 *   warrantyPrice=0-{원}                           보증금 상한 ★ 사용자의 전세금을 넣는다
 *   center={base62(경도)}-{base62(위도)}            지도 중심 ★ 아래 인코딩으로 생성
 *   zoom=14
 *
 * ── center 인코딩 (역산·검증 완료) ──
 *   center = enc(경도×1e7 + 2e9) + "-" + enc(위도×1e7 + 2e9)
 *   enc = base62, 문자셋 "0-9 a-z A-Z", 6자리 좌측 0패딩
 *   오프셋 2e9는 음수 좌표를 없애기 위한 것 (경도 -180 → 2e8, +180 → 3.8e9)
 *
 *   검증: 네이버가 만든 "3zfQf6-2AHIg8" → (37.4632, 126.9346) → 재인코딩 시 완전 일치.
 *        실기기에서 광주 치평동 좌표로 만든 링크가 정확히 치평동으로 이동함을 확인.
 */

const NAVER_LAND = "https://fin.land.naver.com/map";
const NON_APT_TYPES = "A05-A06-A07-C02-C03-C01-A02";

const B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const COORD_OFFSET = 2_000_000_000;

function enc6(v) {
  let s = "";
  let n = v;
  while (n > 0) {
    s = B62[n % 62] + s;
    n = Math.floor(n / 62);
  }
  return s.padStart(6, "0");
}

/** 위경도 → 네이버 center 값 */
export function naverCenter(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const lo = Math.round(lon * 1e7) + COORD_OFFSET;
  const la = Math.round(lat * 1e7) + COORD_OFFSET;
  return `${enc6(lo)}-${enc6(la)}`;
}

/** center → 위경도 (테스트·검증용) */
export function readNaverCenter(center) {
  if (!center || !center.includes("-")) return null;
  const [a, b] = center.split("-");
  const dec = (s) => [...s].reduce((v, ch) => v * 62 + B62.indexOf(ch), 0);
  return { lat: (dec(b) - COORD_OFFSET) / 1e7, lon: (dec(a) - COORD_OFFSET) / 1e7 };
}

/**
 * 네이버 부동산 딥링크 — 전세 + 비아파트 + 보증금 상한 (+ 좌표가 있으면 그 동네로)
 * @param {number} depositCap 보증금 상한(원)
 * @param {{lat:number, lon:number}} [coord] 동네 중심좌표. 없으면 지도 위치는 네이버 기본값.
 */
export function naverLandUrl(depositCap, coord) {
  const cap = Math.max(0, Math.round(depositCap || 0));
  const params = new URLSearchParams({
    zoom: "14",
    tradeTypes: "B1",
    realEstateTypes: NON_APT_TYPES,
  });
  if (cap > 0) params.set("warrantyPrice", `0-${cap}`);
  if (coord && Number.isFinite(coord.lat) && Number.isFinite(coord.lon)) {
    params.set("center", naverCenter(coord.lat, coord.lon));
  }
  return `${NAVER_LAND}?${params.toString()}`;
}

/** 네이버 통합검색 — 폴백 */
export function naverSearchUrl(regionName, dong, keyword = "빌라 전세") {
  const q = [regionName, dong, keyword].filter(Boolean).join(" ");
  return `https://search.naver.com/search.naver?query=${encodeURIComponent(q)}`;
}
