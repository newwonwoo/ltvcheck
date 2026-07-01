// 동명이지(同名異地) — 같은 동 이름이 여러 지역에 있을 때 후보를 보여주고 고르게 한다.
// 잘못된 지역으로 단정하지 않기 위한 정직한 단계.

export default function RegionPicker({ regions, onPick, show }) {
  return (
    <section className={"result" + (show ? " show" : "")} aria-live="polite">
      <div className="region-head">
        <span className="region-icon" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0Z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
        </span>
        <div>
          <p className="region-main">같은 이름의 지역이 여러 곳이에요</p>
          <p className="region-sub">어느 지역인지 골라 주세요. 정확한 공시가를 찾아 드릴게요.</p>
        </div>
      </div>
      <div className="region-list">
        {regions.map((c, i) => (
          <button key={i} className="region-item" onClick={() => onPick(c)}>
            <span className="region-name">
              {[c["시도"], c["시군구"], c["읍면동"]].filter(Boolean).join(" ")}
            </span>
            <span className="region-meta">
              {c["대표주소"] || ""}{c["우편번호"] ? ` · ${c["우편번호"]}` : ""}
            </span>
            <span className="region-arrow" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
