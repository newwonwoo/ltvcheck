import { useState, useEffect } from "react";

/**
 * 공시가 1억 이하 주택 찾기 (비적재 방식)
 * - 지역(시군구) 선택 → public/data/low/{코드}.json fetch
 * - 이미 1억 미만만 담긴 파일이라 조회 시 필터 최소(유형/면적/정렬만)
 * - ㎡당 공시가 표시(특히 다세대 비교용)
 */
const won = (n) =>
  n >= 100000000
    ? `${(n / 100000000).toFixed(2)}억`
    : `${Math.round(n / 10000).toLocaleString()}만`;

const TYPES = ["전체", "아파트", "연립", "다세대"];
const AREAS = [
  { label: "면적 전체", min: 0, max: 9999 },
  { label: "~ 40㎡", min: 0, max: 40 },
  { label: "40 ~ 60㎡", min: 40, max: 60 },
  { label: "60㎡ ~", min: 60, max: 9999 },
];

export default function LowPriceFinder() {
  const [index, setIndex] = useState(null);   // 지역 목록
  const [code, setCode] = useState("");        // 선택 시군구
  const [data, setData] = useState(null);      // 선택 지역 데이터
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [typeSel, setTypeSel] = useState("전체");
  const [areaSel, setAreaSel] = useState(0);
  const [sortBy, setSortBy] = useState("price"); // price | perM2
  const [visibleCount, setVisibleCount] = useState(300);

  // 지역 인덱스 로드
  useEffect(() => {
    fetch("/data/low/_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((j) => setIndex(j))
      .catch(() => setErr("지역 목록을 불러오지 못했어요."));
  }, []);

  async function loadRegion(c) {
    setCode(c);
    setData(null);
    setVisibleCount(300);
    setErr("");
    if (!c) return;
    setLoading(true);
    try {
      const r = await fetch(`/data/low/${c}.json`);
      if (!r.ok) throw new Error();
      setData(await r.json());
    } catch {
      setErr("이 지역 데이터가 아직 없어요. (데이터 준비 후 표시됩니다)");
    } finally {
      setLoading(false);
    }
  }

  // 필터 + 정렬
  const area = AREAS[areaSel];
  const hasArea = (it) => it.area != null && it.area > 0;
  const items = (data?.items || [])
    .filter((it) => typeSel === "전체" || it.type === typeSel)
    // 면적 필터가 걸리면 면적 없는 행은 제외(면적 전체=0~9999일 땐 유지)
    .filter((it) => {
      if (area.min === 0 && area.max === 9999) return true;
      return hasArea(it) && it.area >= area.min && it.area < area.max;
    })
    .sort((a, b) => {
      if (sortBy === "perM2") {
        // ㎡당 정렬: 면적 없는(perM2 없는) 행은 뒤로
        if (a.perM2 == null) return 1;
        if (b.perM2 == null) return -1;
        return a.perM2 - b.perM2;
      }
      return a.price - b.price;
    });

  // ㎡당 중위값 — 면적(perM2) 확인된 행만
  const withPerM2 = items.filter((x) => x.perM2 != null);
  const median = (() => {
    const ps = withPerM2.map((x) => x.perM2).sort((a, b) => a - b);
    if (!ps.length) return null;
    return ps[Math.floor(ps.length / 2)];
  })();

  return (
    <div className="low">
      <section className="intro">
        <span className="eyebrow"><span className="dot" />공시가격 1억 이하</span>
        <h1 className="headline">
          공시가격 <span className="accent">1억 이하</span> 주택
          <br />한눈에 찾아보기
        </h1>
        <p className="lede">
          지역을 고르면 공시가격 1억 이하인 공동주택(아파트·연립·다세대)을 보여드려요.
          전용면적당 공시가격도 함께 확인할 수 있어요.
        </p>
      </section>

      <section className="panel">
        <label className="field-label">지역 선택</label>
        <select
          className="region-select"
          value={code}
          onChange={(e) => loadRegion(e.target.value)}
        >
          <option value="">시·군·구를 선택하세요</option>
          {(index?.regions || []).map((r) => (
            <option key={r.code} value={r.code}>
              {r.region} ({r.count.toLocaleString()}건)
            </option>
          ))}
        </select>

        {code && (
          <>
            <div className="filter-row">
              <div className="filter-group">
                <span className="filter-label">유형</span>
                <div className="seg">
                  {TYPES.map((t) => (
                    <button
                      key={t}
                      className={"seg-btn" + (typeSel === t ? " on" : "")}
                      onClick={() => { setTypeSel(t); setVisibleCount(300); }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="filter-row">
              <div className="filter-group">
                <span className="filter-label">전용면적</span>
                <div className="seg">
                  {AREAS.map((a, i) => (
                    <button
                      key={i}
                      className={"seg-btn" + (areaSel === i ? " on" : "")}
                      onClick={() => { setAreaSel(i); setVisibleCount(300); }}
                    >
                      {a.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}
      </section>

      {err && <div className="low-note">{err}</div>}
      {loading && <div className="low-note">불러오는 중…</div>}

      {data && !loading && (
        <section className="low-result">
          <div className="low-head">
            <div>
              <strong>{data.region}</strong> · {typeSel}
              <span className="low-count"> {items.length.toLocaleString()}건</span>
            </div>
            <div className="low-sort">
              <button
                className={sortBy === "price" ? "on" : ""}
                onClick={() => setSortBy("price")}
              >공시가순</button>
              <button
                className={sortBy === "perM2" ? "on" : ""}
                onClick={() => setSortBy("perM2")}
              >㎡당순</button>
            </div>
          </div>

          {median && (
            <div className="low-median">
              동일 조건 ㎡당 공시가격 중위값 <strong>{won(median)}원</strong>
              <span className="low-median-hint">
                {" "}· 전용면적이 확인된 {withPerM2.length.toLocaleString()}건 기준
              </span>
            </div>
          )}

          <div className="low-list">
            {items.slice(0, visibleCount).map((it, i) => (
              <div className="low-card" key={i}>
                <div className="low-card-top">
                  <span className={"ptag " + it.type}>{it.type}</span>
                  <span className="low-name">
                    {it.dong} {it.name}
                    {it.bldDong ? ` ${it.bldDong}동` : ""}
                    {it.ho ? ` ${it.ho}호` : ""}
                  </span>
                </div>
                <div className="low-card-body">
                  <div className="low-metric">
                    <span className="lm-label">전용</span>
                    <span className="lm-val">{it.area != null && it.area > 0 ? `${it.area}㎡` : "—"}</span>
                  </div>
                  <div className="low-metric">
                    <span className="lm-label">공시가</span>
                    <span className="lm-val">{won(it.price)}원</span>
                  </div>
                  <div className="low-metric hl">
                    <span className="lm-label">㎡당</span>
                    <span className="lm-val">{it.perM2 != null ? `${won(it.perM2)}원` : "계산 불가"}</span>
                  </div>
                </div>
              </div>
            ))}
            {items.length > visibleCount && (
              <button className="low-more" onClick={() => setVisibleCount((n) => n + 300)}>
                더 보기 ({visibleCount.toLocaleString()} / {items.length.toLocaleString()}건)
              </button>
            )}
            {items.length === 0 && (
              <div className="low-note">조건에 맞는 주택이 없어요. 필터를 바꿔 보세요.</div>
            )}
          </div>
        </section>
      )}

      <footer className="foot">
        <div className="src">국토교통부 공동주택 공시가격 (공시기준일 1월 1일)</div>
        <div>공시가격 1억 이하 공동주택 정보 · 참고용이며 실제 거래·보증 판단은 별도 확인이 필요합니다</div>
      </footer>
    </div>
  );
}
