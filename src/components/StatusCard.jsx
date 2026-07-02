// 조회 실패·빈 결과를 정직하게 안내하는 카드.
// 목업으로 메우지 않고, 무엇이 왜 안 됐는지 + 다음 행동을 알려준다.

export default function StatusCard({ kind, title, message, show }) {
  const isError = kind === "error";
  return (
    <section className={"result" + (show ? " show" : "")} aria-live="polite">
      <div className="status-card">
        <span className={"status-icon " + (isError ? "err" : "empty")}>
          {isError ? (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18.36 6.64A9 9 0 1 1 5.64 6.64" />
              <line x1="12" y1="2" x2="12" y2="12" />
            </svg>
          ) : (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
          )}
        </span>
        <div className="status-text">
          <p className="status-main">{title || (isError ? "조회를 마치지 못했어요" : "결과를 찾지 못했어요")}</p>
          <p className="status-sub">{message}</p>
        </div>
      </div>
    </section>
  );
}
