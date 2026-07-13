import { useState, useEffect, useMemo } from "react";
import {
  POLICY, evaluateArea, requiredPrice, parseMoney, formatMoney, GRADES,
} from "../utils/guarantee";
import { naverLandUrl } from "../utils/links";

const GRADE_ORDER = ["GOOD", "MID", "HARD"];
const GRADE_DESC = {
  GOOD: "대부분 집이 조건을 넘어요",
  MID: "되는 집도 있고 안 되는 집도 있어요",
  HARD: "조건을 넘는 집이 많지 않아요",
};

export default function AreaFinder() {
  const [depositRaw, setDepositRaw] = useState("");
  const [seniorRaw, setSeniorRaw] = useState("");
  const [sido, setSido] = useState("");
  const [gu, setGu] = useState(null);        // 선택한 구 {code, region, short}
  const [index, setIndex] = useState(null);
  const [guData, setGuData] = useState(null); // 구 상세(동네별)
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(null); // 방금 복사한 동네

  const deposit = parseMoney(depositRaw);
  const senior = parseMoney(seniorRaw) || 0;
  const need = deposit ? requiredPrice(deposit, senior) : 0;

  useEffect(() => {
    fetch("/data/area/_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setIndex)
      .catch(() => setErr("지역 데이터를 불러오지 못했어요."));
  }, []);

  // 구 선택 → 동네 데이터
  useEffect(() => {
    if (!gu) { setGuData(null); return; }
    setLoading(true);
    fetch(`/data/area/${gu.code}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setGuData)
      .catch(() => setErr("이 지역의 동네 데이터가 없어요."))
      .finally(() => setLoading(false));
  }, [gu]);

  // 구별 등급 (시도 선택 시)
  const guList = useMemo(() => {
    if (!index || !deposit || !sido) return null;
    return index.regions
      .filter((r) => r.sido === sido && r.hist)
      .map((r) => evaluateArea(r, deposit, senior, index.binSize, index.binMax))
      .filter((r) => r.ratio != null)
      .sort((a, b) => b.ratio - a.ratio);
  }, [index, deposit, senior, sido]);

  // 동네별 등급 (구 선택 시)
  const dongList = useMemo(() => {
    if (!guData || !deposit) return null;
    return guData.areas
      .map((a) => evaluateArea(a, deposit, senior, guData.binSize, guData.binMax))
      .filter((a) => a.ratio != null)
      .sort((a, b) => b.ratio - a.ratio);
  }, [guData, deposit, senior]);

  // 좌표가 있으면 그 동네로 바로 가는 딥링크를 연다(center 인코딩 역산 완료).
  // 좌표가 없는 데이터(지오코딩 미실행)면 필터만 걸고 동네명을 복사해 둔다.
  async function openNaver(area) {
    const coord = Number.isFinite(area.lat) && Number.isFinite(area.lon)
      ? { lat: area.lat, lon: area.lon }
      : null;
    if (!coord) {
      try {
        await navigator.clipboard.writeText(area.dong);
        setCopied(area.dong);
        setTimeout(() => setCopied(null), 2500);
      } catch { /* 실패해도 링크는 연다 */ }
    }
    window.open(naverLandUrl(deposit, coord), "_blank", "noopener,noreferrer");
  }

  function groupByGrade(list) {
    const g = { GOOD: [], MID: [], HARD: [] };
    for (const a of list) g[a.grade.key].push(a);
    return g;
  }

  return (
    <div className="area">
      <div className="area-head">
        <h3>내 전세금으로 갈 만한 동네</h3>
        <p className="area-sub">
          전세금을 넣으면 <strong>구 → 동네</strong> 순으로 공시가 기준 보증 가능성을 보여드려요.
          연립·다세대 기준이에요.
        </p>
      </div>

      {/* 입력 */}
      <div className="area-inputs">
        <div className="area-field">
          <label className="field-label">전세보증금</label>
          <input
            className="input" inputMode="numeric"
            placeholder="예: 2억, 1억 8천, 180000000"
            value={depositRaw} onChange={(e) => setDepositRaw(e.target.value)}
          />
          {depositRaw && (
            <div className={"area-hint" + (deposit ? "" : " bad")}>
              {deposit ? formatMoney(deposit) : "금액을 알아보지 못했어요"}
            </div>
          )}
        </div>

        <div className="area-field">
          <label className="field-label">
            선순위채권 <span className="opt">(집주인 대출·근저당)</span>
          </label>
          <input
            className="input" inputMode="numeric"
            placeholder="모르면 비워두세요 (예: 5천)"
            value={seniorRaw} onChange={(e) => setSeniorRaw(e.target.value)}
          />
          <div className="area-hint sub">
            {seniorRaw && parseMoney(seniorRaw)
              ? formatMoney(parseMoney(seniorRaw))
              : "집을 정했다면 [등기부 확인] 탭에서 채권최고액을 확인해 넣어주세요"}
          </div>
        </div>

        <div className="area-field">
          <label className="field-label">시·도</label>
          <select
            className="input" value={sido}
            onChange={(e) => { setSido(e.target.value); setGu(null); }}
          >
            <option value="">시·도를 고르세요</option>
            {(index?.sido || []).map((s) => (
              <option key={s.code} value={s.code}>{s.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* 기준 */}
      {deposit > 0 && (
        <div className="area-need">
          <div className="area-need-row">
            <span>전세금 {formatMoney(deposit)}</span>
            {senior > 0 && <span>+ 선순위 {formatMoney(senior)}</span>}
          </div>
          <div className="area-need-main">
            공시가격 <strong>{formatMoney(need)} 이상</strong>인 집이어야 해요
          </div>
          <div className="area-need-formula">
            {POLICY.label} · 공시가 × 140% × 90% = 126%
          </div>
        </div>
      )}

      {err && <div className="area-err">{err}</div>}
      {loading && <div className="area-loading">불러오는 중…</div>}

      {/* 1단계: 구 후보 */}
      {!gu && guList && (
        <div className="area-result">
          <div className="area-level">구 후보 {guList.length}곳</div>
          {GRADE_ORDER.map((key) => {
            const list = groupByGrade(guList)[key];
            if (!list.length) return null;
            const g = GRADES[key];
            return (
              <div className="area-group" key={key}>
                <div className="area-group-head">
                  <span className="area-group-icon">{g.icon}</span>
                  <span className="area-group-label">{g.label}</span>
                  <span className="area-group-desc">{GRADE_DESC[key]}</span>
                </div>
                {list.map((r) => (
                  <button
                    className={"area-card tap " + key.toLowerCase()}
                    key={r.code}
                    onClick={() => setGu(r)}
                  >
                    <div className="area-card-top">
                      <span className="area-dong">{r.short}</span>
                      <span className="area-ratio">{Math.round(r.ratio * 100)}%</span>
                    </div>
                    <div className="area-bar">
                      <div className={"area-bar-fill " + key.toLowerCase()}
                           style={{ width: `${Math.round(r.ratio * 100)}%` }} />
                    </div>
                    <div className="area-card-meta">
                      <span>평균 {formatMoney(r.avg)}</span>
                      <span>{r.count.toLocaleString()}세대 · 동네 {r.areaCount}곳 ›</span>
                    </div>
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {/* 2단계: 동네 */}
      {gu && dongList && (
        <div className="area-result">
          <button className="area-back" onClick={() => setGu(null)}>‹ 구 목록으로</button>
          <div className="area-level">{gu.region} · 동네 {dongList.length}곳</div>
          <div className="area-naver-tip">
            {dongList.some((a) => Number.isFinite(a.lat)) ? (
              <>네이버를 누르면 <strong>그 동네 지도</strong>가 바로 열려요.
                <strong> 전세 · 빌라 · 보증금 {formatMoney(deposit)} 이하</strong> 필터도 이미 걸려 있어요.</>
            ) : (
              <>네이버로 넘어가면 <strong>전세 · 빌라 · 보증금 {formatMoney(deposit)} 이하</strong> 필터가
                이미 걸려 있어요. 동네 이름은 자동으로 복사되니 상단 검색에 붙여넣기만 하면 돼요.</>
            )}
          </div>
          {GRADE_ORDER.map((key) => {
            const list = groupByGrade(dongList)[key];
            if (!list.length) return null;
            const g = GRADES[key];
            return (
              <div className="area-group" key={key}>
                <div className="area-group-head">
                  <span className="area-group-icon">{g.icon}</span>
                  <span className="area-group-label">{g.label}</span>
                  <span className="area-group-desc">{GRADE_DESC[key]}</span>
                </div>
                {list.map((a) => (
                  <div className={"area-card " + key.toLowerCase()} key={a.dong}>
                    <div className="area-card-top">
                      <span className="area-dong">{a.dong}</span>
                      <span className="area-ratio">{Math.round(a.ratio * 100)}%</span>
                    </div>
                    <div className="area-bar">
                      <div className={"area-bar-fill " + key.toLowerCase()}
                           style={{ width: `${Math.round(a.ratio * 100)}%` }} />
                    </div>
                    <div className="area-card-meta">
                      <span>평균 공시가 {formatMoney(a.avg)}</span>
                      <span>{a.count.toLocaleString()}세대</span>
                    </div>
                    <div className="area-card-note">
                      이 동네 평균이면 전세 <strong>{formatMoney(a.avgMaxDeposit)}</strong>까지
                    </div>
                    <button className="area-link" onClick={() => openNaver(a)}>
                      {copied === a.dong
                        ? `'${a.dong}' 복사됨 · 네이버에서 붙여넣기 ↗`
                        : `네이버에서 ${a.dong} 전세 보기 ↗`}
                    </button>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {index && !deposit && (
        <div className="area-empty">전세보증금을 입력하면 갈 만한 구부터 보여드려요.</div>
      )}
      {deposit > 0 && !sido && (
        <div className="area-empty">시·도를 고르면 구별로 보여드려요.</div>
      )}

      <p className="area-foot">
        동네 평균·분포는 공시가격 기준 참고값이에요. 실제 보증 가능 여부는 그 집의 공시가격,
        선순위채권, 권리관계, 계약·임대인 요건에 따라 달라져요. 아파트는 시세 기준이라 제외했어요.
      </p>
    </div>
  );
}
