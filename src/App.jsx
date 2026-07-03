import { useState, useRef } from "react";
import Result from "./components/Result.jsx";
import StatusCard from "./components/StatusCard.jsx";
import RegionPicker from "./components/RegionPicker.jsx";
import { SAMPLES } from "./data/samples.js";

export default function App() {
  const [addr, setAddr] = useState("");
  const [dong, setDong] = useState("");
  const [ho, setHo] = useState("");
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState(null); // {kind:'error'|'empty', message, raw}
  const [regions, setRegions] = useState(null); // 동명이지 후보 리스트
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [compact, setCompact] = useState(false);
  const [isSample, setIsSample] = useState(false);
  const [unitNeeded, setUnitNeeded] = useState(false);
  const addrRef = useRef(null);
  const resultRef = useRef(null);

  // 백엔드(/api/lookup)가 돌려주는 LookupResult → 화면 데이터로 변환
  function adaptApiResult(r) {
    if (!r || !r.ok) return null;
    const t = r.property_type || "공동주택";
    return {
      type: t,
      typeKo: t, // 실제 종류(아파트/연립/다세대/오피스텔) 그대로
      isTarget: r.is_target !== false, // 아파트면 false
      addr: r.refined_address || "",
      name: r.building_name || "조회 결과",
      last: r.price_last,
      now: r.price_this,
      area: "—",
      pnu: r.pnu || "—",
      grade: r.confidence_grade || "B",
    };
  }

  function reveal(data, sample = false) {
    setStatus(null);
    setRegions(null);
    setUnitNeeded(false);
    setResult(data);
    setIsSample(sample);
    setCompact(true);
    setShow(false);
    requestAnimationFrame(() => {
      setShow(true);
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  function revealStatus(kind, title, message) {
    setResult(null);
    setRegions(null);
    setStatus({ kind, title, message });
    setCompact(true);
    setShow(false);
    requestAnimationFrame(() => {
      setShow(true);
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  function revealRegions(list) {
    setResult(null);
    setStatus(null);
    setRegions(list);
    setCompact(true);
    setShow(false);
    requestAnimationFrame(() => {
      setShow(true);
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  // 동명이지 후보를 고르면, 시/도·시군구를 앞에 붙여 재조회
  function pickRegion(c) {
    // 후보의 정확한 대표주소로 직접 조회(원래 입력을 재검색하면 또 같은 후보가 나옴)
    const target = c["대표주소"] || [c["시도"], c["시군구"], c["읍면동"]].filter(Boolean).join(" ");
    setAddr(target);
    setRegions(null);
    setTimeout(() => runWith(target, dong.trim(), ho.trim()), 0);
  }

  function pickSample(i) {
    const s = SAMPLES[i];
    setAddr(s.addr + " " + s.name.split(" ")[0]);
    reveal(s, true); // 샘플임을 표시
  }

  async function run() {
    const q = addr.trim();
    if (!q) {
      addrRef.current?.focus();
      return;
    }
    runWith(q, dong.trim(), ho.trim());
  }

  async function runWith(query, d = "", h = "") {
    const q = (query || "").trim();
    if (!q) return;
    setLoading(true);
    setStatus(null);
    try {
      const res = await fetch("/api/lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q, dong: d, ho: h }),
      });
      if (!res.ok) {
        revealStatus("error", "조회를 마치지 못했어요", "조회 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.");
        return;
      }
      const json = await res.json();
      // 동명이지: 여러 지역 후보 → 선택 UI로
      if (json.ambiguous && json.region_candidates?.length) {
        revealRegions(json.region_candidates);
        return;
      }
      // 여러 세대 → 동·호 입력 필수(임의 대표값 안 씀)
      if (json.needs_unit) {
        const nm = json.building_name || "이 건물";
        revealStatus(
          "empty",
          "동·호를 입력해 주세요",
          `‘${nm}’은(는) 세대가 여러 개예요. 정확한 공시가격은 세대마다 달라서, 동·호를 입력해야 특정할 수 있어요.`
        );
        setUnitNeeded(true);
        return;
      }
      const data = adaptApiResult(json);
      if (data && data.now != null) {
        reveal(data); // 아파트 포함 값은 항상 표시(안내 문구만 종류별로 다름)
      } else {
        const d = diagnose(json);
        revealStatus(d.kind, d.title, d.message, json);
      }
    } catch {
      revealStatus("error", "조회를 마치지 못했어요", "네트워크 오류로 조회하지 못했어요. 연결을 확인해 주세요.");
    } finally {
      setLoading(false);
    }
  }

  // 백엔드 warnings를 사용자 메시지로 번역
  function diagnose(json) {
    const w = (json && json.warnings) || [];
    const has = (s) => w.some((x) => x.includes(s));
    const addrFound = !!(json && json.pnu); // 주소 정제 성공 여부

    // 공시가 인증오류 — 주소는 찾았으나 공시가 서버가 막힌 경우
    if (has("INCORRECT_KEY") || has("INVALID_KEY") || has("인증")) {
      return {
        kind: "error",
        title: addrFound ? "주소는 확인했어요 · 공시가만 못 불러왔어요" : "공시가를 불러오지 못했어요",
        message:
          (addrFound ? `‘${json.refined_address || ""}’ 주소는 찾았어요. ` : "") +
          "다만 공시가격 조회가 지금 막혀 있어요. (관리자: 공시가 API 인증 확인 필요)",
      };
    }
    // 주소 자체를 못 찾음
    if (!addrFound || has("정제 실패") || has("juso")) {
      return {
        kind: "empty",
        title: "주소를 찾지 못했어요",
        message: "도로명 또는 지번 주소를 다시 확인해 주세요. (예: 영등포구 도신로29길 28)",
      };
    }
    // 주소는 찾았으나 공시가 데이터가 없음(아파트/비대상 등)
    if (has("공시가격 미확인") || has("없음") || has("오피스텔")) {
      const isApt = json.property_type == null && addrFound;
      return {
        kind: "empty",
        title: "공시가격 정보가 없어요",
        message: isApt
          ? "아파트이거나 공시 대상이 아닐 수 있어요. 이 서비스는 연립·다세대·오피스텔의 공시가만 안내해요."
          : "이 주소의 공시가격 정보를 찾지 못했어요. 오피스텔이면 잠시 후 다시 시도해 주세요.",
      };
    }
    return {
      kind: "empty",
      title: "결과를 가져오지 못했어요",
      message: "동·호를 함께 입력하면 정확도가 올라가요.",
    };
  }

  return (
    <div className="wrap">
      {/* 헤더 */}
      <header className="brand">
        <div className="brand-mark" aria-hidden="true" />
        <span className="brand-name">전세보증 한도 미리보기</span>
        <span className="brand-tag">· 공시가 변동 안내</span>
      </header>

      {/* 인트로 */}
      <section className="intro">
        <span className="eyebrow">
          <span className="dot" />연립 · 다세대 · 오피스텔
        </span>
        <h1 className="headline">
          공시가격이 바뀌면
          <br />
          <span className="accent">보증 한도</span>도 달라질 수 있어요
        </h1>
        <p className="lede">
          주소만 넣으면 작년과 올해 공시가격이 얼마나 달라졌는지 미리 확인해 드려요.
          갱신 전에 미리 준비할 수 있게요.
        </p>
      </section>

      {/* 입력 */}
      <section className={"panel" + (compact ? " compact" : "")} aria-label="주소 입력">
        <label className="field-label" htmlFor="addr">집 주소</label>
        <div className="addr-field">
          <span className="pin" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0Z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
          </span>
          <input
            id="addr"
            ref={addrRef}
            className="addr-input"
            type="text"
            autoComplete="off"
            placeholder="도로명 또는 지번 주소를 적어 주세요"
            value={addr}
            onChange={(e) => setAddr(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
          />
        </div>
        <div className="sub-row">
          <div className="col">
            <input className={"addr-input" + (unitNeeded ? " need" : "")} type="text" autoComplete="off"
              placeholder={unitNeeded ? "동 · 숫자만 (예: 105)" : "동 (선택)"}
              value={dong} onChange={(e) => setDong(e.target.value)} />
          </div>
          <div className="col">
            <input className={"addr-input" + (unitNeeded ? " need" : "")} type="text" autoComplete="off"
              placeholder={unitNeeded ? "호 · 숫자만 (예: 1403)" : "호 (선택)"}
              value={ho} onChange={(e) => setHo(e.target.value)} />
          </div>
        </div>

        <div className="chips">
          <span className="chip-label">예시로 보기</span>
          <button className="chip" onClick={() => pickSample(0)}>청운벽산빌리지</button>
          <button className="chip" onClick={() => pickSample(1)}>에비앙하우스 201호</button>
          <button className="chip" onClick={() => pickSample(2)}>인터시티오피스텔 201호</button>
        </div>

        <button className="cta" onClick={run} disabled={loading}>
          {loading ? "조회 중…" : "올해 변화 보기"}
          {!loading && (
            <span className="arrow" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </span>
          )}
        </button>
      </section>

      {/* 결과 / 상태 / 동명이지 후보 */}
      <div ref={resultRef}>
        {regions ? (
          <RegionPicker regions={regions} onPick={pickRegion} show={show} />
        ) : status ? (
          <StatusCard kind={status.kind} message={status.message} show={show} />
        ) : (
          <Result data={result} show={show} isSample={isSample} />
        )}
      </div>

      {/* 푸터 */}
      <footer className="foot">
        <div className="src">국토교통부 공동주택가격 · 국세청 상업용건물/오피스텔 기준시가</div>
        <div>주소 정제 행정안전부 · 시세 없는 주택(연립·다세대·오피스텔)의 공시가 변동만 안내합니다</div>
      </footer>
    </div>
  );
}
