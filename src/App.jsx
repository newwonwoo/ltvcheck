import { useState, useRef } from "react";
import Result from "./components/Result.jsx";
import { SAMPLES } from "./data/samples.js";

export default function App() {
  const [addr, setAddr] = useState("");
  const [dong, setDong] = useState("");
  const [ho, setHo] = useState("");
  const [result, setResult] = useState(null);
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [compact, setCompact] = useState(false);
  const [sampleIdx, setSampleIdx] = useState(0);
  const addrRef = useRef(null);
  const resultRef = useRef(null);

  // 백엔드(/api/lookup)가 돌려주는 LookupResult → 화면 데이터로 변환
  function adaptApiResult(r) {
    if (!r || !r.ok) return null;
    return {
      type: r.property_type || "공동주택",
      typeKo: r.property_type === "오피스텔" ? "오피스텔" : "연립·다세대",
      addr: r.refined_address || "",
      name: r.building_name || "조회 결과",
      last: r.price_last,
      now: r.price_this,
      area: "—",
      pnu: r.pnu || "—",
      grade: r.confidence_grade || "B",
    };
  }

  function reveal(data) {
    setResult(data);
    setCompact(true);
    setShow(false);
    requestAnimationFrame(() => {
      setShow(true);
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  function pickSample(i) {
    setSampleIdx(i);
    const s = SAMPLES[i];
    setAddr(s.addr + " " + s.name.split(" ")[0]);
    reveal(s);
  }

  async function run() {
    const q = [addr, dong, ho].filter(Boolean).join(" ").trim();
    if (!q) {
      addrRef.current?.focus();
      return;
    }
    // 백엔드 연결 시도. 실패하거나 미연결이면 현재 선택 샘플로 폴백(데모).
    setLoading(true);
    try {
      const res = await fetch("/api/lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q }),
      });
      if (res.ok) {
        const json = await res.json();
        const data = adaptApiResult(json);
        if (data && data.now != null) {
          reveal(data);
          return;
        }
      }
      // 백엔드 미연결/빈 결과 → 데모 샘플
      reveal(SAMPLES[sampleIdx]);
    } catch {
      reveal(SAMPLES[sampleIdx]);
    } finally {
      setLoading(false);
    }
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
            <input className="addr-input" type="text" autoComplete="off" placeholder="동 (선택)"
              value={dong} onChange={(e) => setDong(e.target.value)} />
          </div>
          <div className="col">
            <input className="addr-input" type="text" autoComplete="off" placeholder="호 (선택)"
              value={ho} onChange={(e) => setHo(e.target.value)} />
          </div>
        </div>

        <div className="chips">
          <span className="chip-label">예시로 보기</span>
          {SAMPLES.map((s, i) => (
            <button key={i} className="chip" onClick={() => pickSample(i)}>
              {s.name.split(" ").slice(0, 1)[0] + (s.name.includes("호") ? " " + s.name.split(" ").pop() : "")}
            </button>
          ))}
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

      {/* 결과 */}
      <div ref={resultRef}>
        <Result data={result} show={show} />
      </div>

      {/* 푸터 */}
      <footer className="foot">
        <div className="src">국토교통부 공동주택가격 · 국세청 상업용건물/오피스텔 기준시가</div>
        <div>주소 정제 행정안전부 · 시세 없는 주택(연립·다세대·오피스텔)의 공시가 변동만 안내합니다</div>
      </footer>
    </div>
  );
}
