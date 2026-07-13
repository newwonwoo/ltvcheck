/**
 * registryParser.js — 등기부등본 파서 (좌표 기반 표 복원)
 *
 * 입력: PDF에서 추출한 텍스트 아이템 [{page, x, y, text}]
 * 출력: 현재 유효한 권리 (근저당 채권최고액, 위험 플래그, 소유자)
 *
 * 왜 좌표가 필요한가 (실물 검증):
 *   줄 단위로 읽으면 표의 셀이 뒤섞인다. 등기목적 한 칸이 여러 줄로 쪼개지고
 *   그 사이에 접수·등기원인이 끼어든다.
 *     14 / "10번가압류," / 2025년7월7일 / "11번압류," / 제3514834호 / "12번강제경매개시결" / ...
 *   컬럼 헤더의 x좌표로 셀을 분류해야 "10번가압류, 11번압류, 12번강제경매개시결정등기말소"로 복원된다.
 *
 * 말소 판단 (실물 검증):
 *   취소선은 PDF 데이터에 없다(색상도 벡터도 아님). 등기목적 칸의 "N번…말소" 텍스트로만 판단.
 *   권리자 칸 본문의 "말소"(예: 공동담보소멸 설명)는 말소가 아니다.
 *
 * 채권최고액 = 등기부 표시금액. 실제 대출잔액이 아니다(등기부에 잔액은 없음).
 */

const HEADERS = ["순위번호", "등기목적", "접수", "등기원인", "권리자및기타사항"];

// 위험 등기 (등기목적 칸에 나올 때만 유효)
const RISK_KINDS = [
  { key: "경매개시", label: "경매개시결정", severity: "CRITICAL" },
  { key: "임의경매", label: "임의경매", severity: "CRITICAL" },
  { key: "강제경매", label: "강제경매", severity: "CRITICAL" },
  { key: "가압류", label: "가압류", severity: "HIGH" },
  { key: "압류", label: "압류", severity: "HIGH" },
  { key: "가처분", label: "가처분", severity: "HIGH" },
  { key: "신탁", label: "신탁", severity: "WARNING" },
  { key: "가등기", label: "가등기", severity: "WARNING" },
  { key: "주택임차권", label: "주택임차권등기", severity: "WARNING" },
  { key: "임차권", label: "임차권등기", severity: "WARNING" },
  { key: "전세권", label: "전세권", severity: "WARNING" },
];

const RE_MAX_CLAIM = /채권\s*최고액\s*금?\s*([\d,]+)\s*원/;
const RE_JEONSE = /(?:임차보증금|전세금)\s*금?\s*([\d,]+)\s*원/;
const RE_UNIQUE = /고유번호\s*([\d-]+)/;
const RE_ADDR = /\[집합건물\]\s*(.+)/;
const RE_SKIP = /^\d+\/\d+$|^열\s*람\s*용$|^열람일시|^\[집합건물\]|^관할등기소|^\*|^--/;

export function parseAmount(s) {
  if (!s) return null;
  const n = parseInt(String(s).replace(/[,\s]/g, ""), 10);
  return Number.isFinite(n) ? n : null;
}

/** 같은 y의 아이템을 '줄'로 묶는다 (PDF.js는 자간 넓은 글자를 낱개로 쪼갠다) */
function groupLines(items) {
  const sorted = [...items].sort(
    (a, b) => (a.page - b.page) || (a.y - b.y) || (a.x - b.x)
  );
  const lines = [];
  let cur = null;
  for (const it of sorted) {
    if (cur && it.page === cur.page && Math.abs(it.y - cur.y) < 4) {
      cur.items.push(it);
    } else {
      cur = { page: it.page, y: it.y, items: [it] };
      lines.push(cur);
    }
  }
  return lines.map((l) => ({ ...l, text: l.items.map((i) => i.text).join(" ") }));
}

/** 헤더 줄의 x좌표에서 컬럼 경계 산출 (간격 30px 이상이면 다른 컬럼) */
function boundsFromHeaderLine(line) {
  const xs = line.items.map((i) => i.x).sort((a, b) => a - b);
  const starts = [xs[0]];
  for (let i = 1; i < xs.length; i++) {
    if (xs[i] - starts[starts.length - 1] > 30) starts.push(xs[i]);
  }
  if (starts.length < 4) return null;
  const bounds = [];
  for (let i = 0; i < starts.length - 1; i++) bounds.push((starts[i] + starts[i + 1]) / 2);
  return bounds;
}

function colOf(x, bounds) {
  for (let i = 0; i < bounds.length; i++) if (x < bounds[i]) return i;
  return bounds.length;
}

/** 표 복원: 아이템 → 순위번호별 행 */
export function restoreTable(items) {
  const lines = groupLines(items);
  const rows = [];
  let cur = null, section = null, bounds = null;

  for (const line of lines) {
    const bare = line.text.replace(/\s/g, "");

    // 컬럼 헤더 줄 → 컬럼 경계 갱신
    if (bare.includes("순위번호") && bare.includes("등기목적")) {
      const b = boundsFromHeaderLine(line);
      if (b) bounds = b;
      continue;
    }
    // 섹션 전환
    if (bare.includes("표제부")) { section = "표제부"; cur = null; continue; }
    if (bare.includes("갑구") && bare.includes("소유권")) { section = "갑구"; cur = null; continue; }
    if (bare.includes("을구") && bare.includes("소유권")) { section = "을구"; cur = null; continue; }
    if (bare.includes("주요등기사항요약")) { section = "요약"; cur = null; continue; }

    if (section !== "갑구" && section !== "을구") continue;
    if (!bounds) continue;

    for (const it of line.items) {
      const t = it.text;
      if (RE_SKIP.test(t)) continue;
      const c = colOf(it.x, bounds);
      if (c === 0) {
        const m = t.match(/^(\d+)(?:-(\d+))?$/);
        if (m) {
          cur = {
            section, rank: parseInt(m[1], 10), sub: m[2] ? parseInt(m[2], 10) : null,
            purpose: [], receipt: [], cause: [], holder: [],
          };
          rows.push(cur);
          continue;
        }
      }
      if (!cur) continue;
      const key = ["_", "purpose", "receipt", "cause", "holder"][Math.min(c, 4)];
      if (key !== "_") cur[key].push(t);
    }
  }

  return rows.map((r) => ({
    ...r,
    purpose: r.purpose.join(" ").trim(),
    receipt: r.receipt.join(" ").trim(),
    cause: r.cause.join(" ").trim(),
    holder: r.holder.join(" ").trim(),
  }));
}

/** 데이터 줄들의 x 분포로 컬럼 경계 산출 (요약표는 헤더가 중앙정렬이라 헤더 x를 못 쓴다) */
function boundsFromDataLines(dataLines) {
  const xs = [];
  for (const l of dataLines) for (const it of l.items) xs.push(it.x);
  xs.sort((a, b) => a - b);
  const starts = [];
  for (const x of xs) {
    if (!starts.length || x - starts[starts.length - 1] > 25) starts.push(x);
  }
  if (starts.length < 4) return null;
  const bounds = [];
  for (let i = 0; i < starts.length - 1; i++) bounds.push((starts[i] + starts[i + 1]) / 2);
  return bounds;
}

/**
 * 주요 등기사항 요약 페이지 파싱 (있는 경우)
 *
 * 요약은 "말소되지 않은 사항"만 정리한 표라서, 본문 파싱 결과를 교차검증하는 데 쓴다.
 *   §1 소유지분현황(갑구): 등기명의인 | 등록번호 | 최종지분 | 주소 | 순위번호
 *   §2 소유권 제한사항(갑구) / §3 (근)저당권·전세권(을구): 순위번호 | 등기목적 | 접수정보 | 주요등기사항 | 대상소유자
 */
export function parseSummary(items) {
  const lines = groupLines(items);
  const out = { present: false, owners: [], rights: [], mortgages: [], mortgageTotal: 0 };

  // 1패스: 요약 페이지의 줄을 섹션별 데이터 줄로 분류
  const buckets = { owners: [], rights: [], mortgages: [] };
  let inSummary = false, sub = null;
  for (const line of lines) {
    const bare = line.text.replace(/\s/g, "");
    if (bare.includes("주요등기사항요약")) { inSummary = true; out.present = true; continue; }
    if (!inSummary) continue;

    if (/^1\.소유지분현황/.test(bare)) { sub = "owners"; continue; }
    if (/^2\.소유지분을제외한/.test(bare)) { sub = "rights"; continue; }
    if (/^3\./.test(bare) && bare.includes("저당권")) { sub = "mortgages"; continue; }
    if (bare.includes("참고사항") || bare.includes("주의사항")) { sub = null; continue; }
    if (!sub) continue;

    // 헤더 줄 제외
    if (bare.includes("등기명의인") || (bare.includes("순위번호") && bare.includes("등기목적"))) continue;
    if (RE_SKIP.test(line.text) || bare.includes("고유번호")) continue;
    buckets[sub].push(line);
  }
  if (!out.present) return out;

  // 2패스: 섹션별로 데이터 x 분포에서 컬럼을 잡고 행 조립
  for (const key of ["owners", "rights", "mortgages"]) {
    const dataLines = buckets[key];
    if (!dataLines.length) continue;
    const bounds = boundsFromDataLines(dataLines);
    if (!bounds) continue;
    let cur = null;

    for (const line of dataLines) {
      const cells = [[], [], [], [], []];
      for (const it of line.items) cells[Math.min(colOf(it.x, bounds), 4)].push(it.text);
      const col = (i) => cells[i].join(" ").trim();

      if (key === "owners") {
        if (/\d{6}-[\d*]+/.test(line.text)) {
          cur = { name: col(0), regNo: col(1), share: col(2), addr: col(3), rank: col(4), raw: line.text };
          out.owners.push(cur);
        } else if (cur) {
          if (col(0)) cur.name += col(0);   // 이름이 두 줄로 쪼개짐
          if (col(3)) cur.addr += " " + col(3);
          cur.raw += " " + line.text;
        }
      } else {
        if (/^\d+(-\d+)?$/.test(col(0))) {
          cur = { rank: col(0), purpose: col(1), receipt: col(2), detail: col(3), owner: col(4), raw: line.text };
          out[key].push(cur);
        } else if (cur) {
          if (col(1)) cur.purpose += col(1);
          if (col(2)) cur.receipt += " " + col(2);
          if (col(3)) cur.detail += " " + col(3);
          if (col(4)) cur.owner += col(4);
          cur.raw += " " + line.text;
        }
      }
    }
  }

  // 금액·채권자·지분은 행 원문(raw)에서 뽑는다.
  // 컬럼 폭이 PDF 생성기마다 달라 셀 분류가 밀릴 수 있으므로, 값 추출은 컬럼에 의존하지 않는다.
  for (const m of out.mortgages) {
    const am = m.raw.match(RE_MAX_CLAIM);
    m.amount = am ? parseAmount(am[1]) : null;
    const cr = m.raw.match(/근저당권자\s*([^\s0-9]+)/);
    m.creditor = cr ? cr[1] : null;
    const je = m.raw.match(RE_JEONSE);
    if (je) m.jeonseAmount = parseAmount(je[1]);
    m.isMortgage = /근저당/.test(m.purpose) || /근저당권설정/.test(m.raw);
  }
  for (const o of out.owners) {
    const sh = o.raw.match(/단독소유|[\d,]+분의\s*[\d,.]+/);
    if (sh) o.share = sh[0];
    const rk = o.raw.match(/(\d+(?:-\d+)?)\s*$/);
    if (rk && !o.rank) o.rank = rk[1];
  }
  out.mortgageTotal = out.mortgages
    .filter((m) => m.isMortgage)
    .reduce((s, m) => s + (m.amount || 0), 0);

  return out;
}

/** 게이트: 등기사항증명서인지 */
export function validateItems(items) {
  if (!items || items.length < 30) return { ok: false, reason: "TEXT_TOO_SHORT" };
  const all = items.map((i) => i.text).join("").replace(/\s/g, "");
  const markers = ["등기사항", "표제부", "권리자및기타사항", "순위번호"];
  const hit = markers.filter((m) => all.includes(m)).length;
  if (hit < 2) return { ok: false, reason: "NOT_REGISTRY_FORMAT" };
  return { ok: true, reason: "OK" };
}

/** 메인 파서 */
export function parseRegistryItems(items) {
  const gate = validateItems(items);
  if (!gate.ok) return { ok: false, status: gate.reason, message: gateMessage(gate.reason) };

  const allText = items.map((i) => i.text).join("\n");
  const uniqueNo = (allText.match(RE_UNIQUE) || [])[1] || null;
  const address = ((allText.match(RE_ADDR) || [])[1] || "").trim() || null;

  const rows = restoreTable(items);

  // 1. 말소 수집: 등기목적 칸에 "말소"가 있으면 그 칸의 모든 "N번"을 말소 처리
  const cancelled = { 갑구: new Set(), 을구: new Set() };
  for (const r of rows) {
    if (!r.purpose.includes("말소")) continue;
    const p = r.purpose.replace(/\s/g, "");
    for (const m of p.matchAll(/(\d+)번(?!길)/g)) {
      if (cancelled[r.section]) cancelled[r.section].add(parseInt(m[1], 10));
    }
  }
  const isCancelled = (r) => (cancelled[r.section] ? cancelled[r.section].has(r.rank) : false);
  const isCancelEvent = (r) => r.purpose.includes("말소");

  // 2. 근저당 (을구)
  const mortgages = [];
  for (const r of rows) {
    if (r.section !== "을구") continue;
    if (!r.purpose.replace(/\s/g, "").includes("근저당권설정")) continue;
    const m = r.holder.match(RE_MAX_CLAIM);
    if (!m) continue;
    mortgages.push({
      rank: r.rank,
      amount: parseAmount(m[1]),
      cancelled: isCancelled(r),
      creditor: (r.holder.match(/근저당권자\s*([^\s0-9]+)/) || [])[1] || null,
    });
  }
  const activeMortgages = mortgages.filter((m) => !m.cancelled);
  const activeMaxClaimTotal = activeMortgages.reduce((s, m) => s + (m.amount || 0), 0);

  // 3. 위험 플래그 (등기목적 기준)
  const flags = [];
  for (const r of rows) {
    if (isCancelEvent(r)) continue;
    const p = r.purpose.replace(/\s/g, "");
    if (p.includes("근저당권설정")) continue;
    for (const risk of RISK_KINDS) {
      if (p.includes(risk.key)) {
        const dup = flags.find((f) => f.section === r.section && f.rank === r.rank);
        if (!dup) {
          const flag = {
            section: r.section, rank: r.rank, kind: risk.label,
            severity: risk.severity, cancelled: isCancelled(r),
          };
          const am = r.holder.match(RE_JEONSE);
          if (am) flag.amount = parseAmount(am[1]);
          flags.push(flag);
        }
        break;
      }
    }
  }
  const activeFlags = flags.filter((f) => !f.cancelled);
  const cancelledFlags = flags.filter((f) => f.cancelled);

  // 4. 현재 소유자
  let owner = null;
  for (const r of rows) {
    if (r.section !== "갑구") continue;
    if (isCancelEvent(r)) continue;
    if (!/소유권(이전|보존)/.test(r.purpose)) continue;
    if (isCancelled(r)) continue;
    const isTrust = r.purpose.includes("신탁") || r.holder.includes("수탁자");
    const nm = r.holder.match(/(?:소유자|수탁자)\s+([^\s]+)/);
    owner = { rank: r.rank, name: nm ? nm[1] : null, isTrust, raw: r.holder.slice(0, 80) };
  }

  // 5. 요약 페이지로 교차검증 (요약은 '말소되지 않은 사항'만 정리한 표라 정답지 역할)
  const summary = parseSummary(items);
  let crossCheck = { available: false };
  if (summary.present) {
    const sumOwner = (summary.owners[0] && summary.owners[0].name) || "";
    const bodyOwner = (owner && owner.name) || "";
    const norm = (v) => v.replace(/\s|\(.*?\)/g, "");
    const ownerMatch =
      !!bodyOwner && !!sumOwner &&
      (norm(sumOwner).includes(norm(bodyOwner)) || norm(bodyOwner).includes(norm(sumOwner)));
    const mortgageMatch = summary.mortgageTotal === activeMaxClaimTotal;
    crossCheck = {
      available: true,
      ok: ownerMatch && mortgageMatch,
      ownerMatch,
      mortgageMatch,
      summaryOwner: sumOwner || null,
      summaryMortgageTotal: summary.mortgageTotal,
    };
  }

  // 6. 종합 위험도
  let riskLevel = "CLEAN";
  if (activeFlags.some((f) => f.severity === "CRITICAL")) riskLevel = "CRITICAL";
  else if (activeFlags.some((f) => f.severity === "HIGH")) riskLevel = "HIGH";
  else if (activeFlags.length > 0 || activeMortgages.length > 0) riskLevel = "HAS_RIGHTS";

  return {
    ok: true,
    status: "PARSED",
    property: { uniqueNo, address },
    owner,
    seniorClaim: {
      activeMaxClaimTotal,
      mortgages: activeMortgages,
      allMortgages: mortgages,
      hasEul: rows.some((r) => r.section === "을구"),
    },
    riskFlags: activeFlags,
    cancelledFlags,
    riskLevel,
    crossCheck,
    summary,
    rows,
    disclaimer:
      "등기부에 표시된 정보 기준이에요. 채권최고액은 실제 대출잔액이 아니고(등기부에 잔액은 없어요), " +
      "실제 채무는 잔액증명서로 확인해야 해요. 최종 판단은 전문가 검토가 필요해요.",
  };
}

function gateMessage(reason) {
  return {
    TEXT_TOO_SHORT:
      "텍스트를 추출하지 못했어요. 스캔본·사진·이미지 PDF는 지원하지 않아요. 인터넷등기소에서 발급한 PDF를 올려주세요.",
    NOT_REGISTRY_FORMAT:
      "등기사항증명서 형식이 아니에요. 인터넷등기소 발급 PDF가 맞는지 확인해 주세요.",
  }[reason] || "이 PDF는 분석할 수 없어요.";
}
