import ValueJourney from "./ValueJourney.jsx";
import { won } from "../utils/format.js";

export default function Result({ data, show, isSample }) {
  if (!data) return null;

  const up = data.now >= data.last;
  const delta = data.now - data.last;
  const pct = (delta / data.last) * 100;
  const hasCompare = data.last != null && data.now != null;

  return (
    <section className={"result" + (show ? " show" : "")} aria-live="polite">
      {isSample && (
        <div className="sample-badge">예시 데이터 — 실제 조회는 주소를 입력하세요</div>
      )}
      <div className="res-head">
        <span className={"res-type " + (data.type === "오피스텔" ? "ofctl" : "gongdong")}>
          {data.typeKo}
        </span>
        <span className="res-addr">{data.addr}</span>
      </div>
      <h2 className="res-name">{data.name}</h2>

      <div className="journey">
        <div className="journey-inner">
          <div className="journey-years">
            <span>{data.lastYear || "작년"}</span>
            <span>{data.nowYear || "올해"}</span>
          </div>
          <ValueJourney last={data.last} now={data.now} />

          {hasCompare && (
            <div className={"delta-card " + (up ? "up" : "down")}>
              <div className="delta-figure">
                <span className="delta-glyph">{up ? "↑" : "↓"}</span>
                <span className="delta-amt tnum">
                  {(up ? "+" : "−") + won(Math.abs(delta))}
                </span>
              </div>
              <span className="delta-pct tnum">
                {(up ? "+" : "−") + Math.abs(pct).toFixed(1) + "%"}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="guide">
        <span
          className="guide-icon"
          style={{
            background: up ? "var(--honey-soft)" : "var(--rose-soft)",
            color: up ? "var(--honey-2)" : "var(--rose-2)",
          }}
        >
          {up ? "🌱" : "🍂"}
        </span>
        <div className="guide-text">
          <p className="g-main">
            {up ? "보증 범위가 늘어날 수 있어요" : "보증 범위가 줄어들 수 있어요"}
          </p>
          <p className="g-sub">
            {up
              ? "다만 공시가격이 오른 만큼 보증료가 함께 오를 수 있어요."
              : "갱신 시 한도가 줄 수 있으니 미리 살펴 두면 좋아요."}
          </p>
        </div>
      </div>

      <div className="meta">
        <span className="meta-item">
          <span className="k">전용</span> <span className="tnum">{data.area}</span>
        </span>
        <span className="meta-dot" />
        <span className="meta-item">
          <span className="k">PNU</span> <span className="tnum">{data.pnu}</span>
        </span>
        <span className="meta-dot" />
        <span className="meta-item">
          <span className="k">신뢰도</span>{" "}
          <span className={"grade " + data.grade}>{data.grade}</span>
        </span>
      </div>

      <div className="notice">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4M12 8h.01" />
        </svg>
        <span>
          공시가격 확정 전 참고용이에요. 실제 보증 한도는 심사를 거쳐 정해지고, 보증료도 함께 달라질 수 있어요.
        </span>
      </div>
    </section>
  );
}
