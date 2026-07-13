import { useState, useMemo } from "react";

/**
 * 세대 선택 — 직접 입력이 먼저, 목록은 보조.
 *
 * 위쪽 동·호 입력칸에 타이핑하면 실시간으로 후보가 좁혀진다.
 * 존재하지 않는 호를 넣으면 "없는 세대"라고 정직하게 말한다.
 * (없는 호수를 물었는데 다른 세대 값을 내주던 과거 버그의 정반대편)
 *
 * data = { name, units: [{dong, ho}], addr }
 * dong/ho = 상위 입력칸의 현재 값 (필터 기준)
 */
const MAX_SHOW = 60; // 너무 많으면 다 그리지 않는다

export default function UnitPicker({ data, dong = "", ho = "", onPick, show }) {
  const units = data?.units || [];
  const hasDong = units.some((u) => u.dong);
  const d = String(dong || "").trim();
  const h = String(ho || "").trim();

  const allDongs = useMemo(
    () => [...new Set(units.map((u) => u.dong).filter(Boolean))],
    [units]
  );

  // 동: 입력이 정확히 존재하면 확정. 아니면 접두 매칭 후보.
  const dongExact = hasDong && allDongs.includes(d) ? d : null;
  const dongMatches = useMemo(
    () => (d ? allDongs.filter((x) => x.startsWith(d)) : allDongs),
    [allDongs, d]
  );
  const [picked, setPicked] = useState(null);
  const activeDong = dongExact || picked;

  // 호: 확정된 동 안에서(동이 없으면 전체) 접두 매칭
  const pool = useMemo(() => {
    if (!hasDong) return units;
    if (!activeDong) return [];
    return units.filter((u) => u.dong === activeDong);
  }, [units, hasDong, activeDong]);

  const hoMatches = useMemo(
    () => (h ? pool.filter((u) => u.ho.startsWith(h)) : pool),
    [pool, h]
  );

  // 없는 호수 판정 — 입력했는데 이 동에 하나도 없다
  const noSuchHo = h && pool.length > 0 && hoMatches.length === 0;
  // 다른 동에는 있나?
  const elsewhere = useMemo(() => {
    if (!noSuchHo || !hasDong) return [];
    return [...new Set(units.filter((u) => u.ho === h).map((u) => u.dong))].slice(0, 6);
  }, [noSuchHo, hasDong, units, h]);

  const dongNeeded = hasDong && !activeDong;

  return (
    <section className={"result" + (show ? " show" : "")} aria-live="polite">
      <div className="unit-pick">
        <div className="unit-head">
          <span className="unit-icon">🏢</span>
          <div>
            <p className="unit-title">{data.name}</p>
            <p className="unit-sub">
              세대가 <strong>{units.length.toLocaleString()}개</strong>예요.
              위에 <strong>동·호를 입력</strong>하면 바로 찾아드려요.
              {" "}모르면 아래에서 골라도 돼요.
              <br />
              공시가격은 세대마다 달라서, 정확히 골라야 해요.
            </p>
          </div>
        </div>

        {/* 동: 아직 확정 안 됨 */}
        {dongNeeded && (
          <div className="unit-block">
            <p className="unit-label">
              동 선택 · {dongMatches.length}개
              {d && <span className="unit-hint"> — '{d}' 로 시작하는 동</span>}
            </p>
            {dongMatches.length === 0 ? (
              <div className="unit-none">
                '{d}'로 시작하는 동이 없어요. 있는 동: {allDongs.slice(0, 8).join(", ")}
                {allDongs.length > 8 ? " …" : ""}
              </div>
            ) : (
              <div className="unit-grid">
                {dongMatches.slice(0, MAX_SHOW).map((x) => (
                  <button key={x} className="unit-btn" onClick={() => setPicked(x)}>
                    {x}동
                  </button>
                ))}
                {dongMatches.length > MAX_SHOW && (
                  <span className="unit-more">외 {dongMatches.length - MAX_SHOW}개…</span>
                )}
              </div>
            )}
          </div>
        )}

        {/* 왜 못 찾았는지 — 추측하지 않고 원문 그대로 보여준다 */}
        {(data.warnings || []).some((w) => /없어요|일부만 조회|여러 동에/.test(w)) && (
          <div className="unit-why">
            {data.warnings
              .filter((w) => /없어요|일부만 조회|여러 동에/.test(w))
              .map((w, i) => (
                <div key={i} className={w.startsWith("★") ? "unit-why-bad" : ""}>{w}</div>
              ))}
          </div>
        )}

        {/* 호 */}
        {!dongNeeded && (
          <div className="unit-block">
            <p className="unit-label">
              호 선택{hasDong ? ` · ${activeDong}동` : ""} · {hoMatches.length}세대
              {h && !noSuchHo && <span className="unit-hint"> — '{h}' 로 시작하는 호</span>}
              {hasDong && !dongExact && (
                <button className="unit-reset" onClick={() => setPicked(null)}>동 다시</button>
              )}
            </p>

            {noSuchHo ? (
              <div className="unit-none warn">
                <strong>
                  {hasDong ? `${activeDong}동에 ` : "이 단지에 "}{h}호는 없어요.
                </strong>
                {elsewhere.length > 0 && (
                  <> {h}호는 {elsewhere.map((x) => `${x}동`).join(", ")}에 있어요.</>
                )}
                <div className="unit-none-sub">
                  {hasDong ? `${activeDong}동에 ` : ""}있는 호: {pool.slice(0, 8).map((u) => u.ho).join(", ")}
                  {pool.length > 8 ? ` … (총 ${pool.length}세대)` : ""}
                </div>
              </div>
            ) : (
              <div className="unit-grid">
                {hoMatches.slice(0, MAX_SHOW).map((u, i) => (
                  <button key={i} className="unit-btn ho" onClick={() => onPick(u)}>
                    {u.ho}호
                  </button>
                ))}
                {hoMatches.length > MAX_SHOW && (
                  <span className="unit-more">
                    외 {hoMatches.length - MAX_SHOW}개… 호를 더 입력하면 좁혀져요
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
