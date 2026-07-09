import { useState } from "react";

/**
 * 여러 세대가 있는 단지에서 실제 존재하는 동·호를 보여주고 고르게 한다.
 * - 동 정보가 있으면: 동 먼저 선택 → 그 동의 호 목록
 * - 동 정보가 없으면(빈 문자열): 호 목록만
 * data = { name, units: [{dong, ho}], addr }
 */
export default function UnitPicker({ data, onPick, show }) {
  const units = data?.units || [];
  const hasDong = units.some((u) => u.dong);
  const dongs = hasDong
    ? [...new Set(units.map((u) => u.dong).filter(Boolean))]
    : [];
  const [sel, setSel] = useState(dongs.length === 1 ? dongs[0] : null);

  // 표시할 호 목록
  const hoList = hasDong
    ? units.filter((u) => u.dong === sel)
    : units;

  return (
    <section className={"result" + (show ? " show" : "")} aria-live="polite">
      <div className="unit-pick">
        <div className="unit-head">
          <span className="unit-icon">🏢</span>
          <div>
            <p className="unit-title">{data.name}</p>
            <p className="unit-sub">
              세대가 여러 개예요. 아래에서 해당 세대를 골라 주세요.
              <br />
              공시가격은 세대마다 달라서, 정확히 골라야 해요.
            </p>
          </div>
        </div>

        {hasDong && (
          <div className="unit-block">
            <p className="unit-label">동 선택</p>
            <div className="unit-grid">
              {dongs.map((d) => (
                <button
                  key={d}
                  className={"unit-btn" + (sel === d ? " on" : "")}
                  onClick={() => setSel(d)}
                >
                  {d}동
                </button>
              ))}
            </div>
          </div>
        )}

        {(!hasDong || sel) && (
          <div className="unit-block">
            <p className="unit-label">
              호 선택{hasDong ? ` (${sel}동)` : ""} · {hoList.length}세대
            </p>
            <div className="unit-grid">
              {hoList.map((u, i) => (
                <button
                  key={i}
                  className="unit-btn ho"
                  onClick={() => onPick(u)}
                >
                  {u.ho}호
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
