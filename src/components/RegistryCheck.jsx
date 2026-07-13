import { useState, useRef } from "react";
import { parseRegistryItems } from "../utils/registryParser";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

// PDF.js worker를 번들에서 로드 (CDN 의존 없음, 등기부는 서버로 안 보냄)
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

// 좌표 포함 추출 — 등기부는 표라서 x좌표로 컬럼을 나눠야 셀이 안 뒤섞임
async function extractItems(file) {
  const buf = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
  const raw = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const viewport = page.getViewport({ scale: 1 });
    const content = await page.getTextContent();
    for (const it of content.items) {
      const t = it.str || "";
      if (!t.trim()) continue;
      raw.push({
        page: i - 1,
        x: it.transform[4],
        y: viewport.height - it.transform[5], // PDF 좌표계(하단 원점) → 위→아래
        text: t.trim(),
      });
    }
  }
  return raw;
}

function won(n) {
  if (n == null) return "-";
  return n.toLocaleString();
}

export default function RegistryCheck({ propertyPrice }) {
  const [state, setState] = useState("idle"); // idle|loading|done|error
  const [result, setResult] = useState(null);
  const [errMsg, setErrMsg] = useState("");
  const fileRef = useRef(null);

  async function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setState("error");
      setErrMsg("PDF 파일만 올릴 수 있어요. 인터넷등기소에서 발급한 등기부 PDF를 사용해 주세요.");
      return;
    }
    setState("loading");
    setErrMsg("");
    try {
      const items = await extractItems(file);
      const parsed = parseRegistryItems(items);
      if (!parsed.ok) {
        setState("error");
        setErrMsg(parsed.message);
        return;
      }
      setResult(parsed);
      setState("done");
    } catch (err) {
      setState("error");
      setErrMsg("PDF를 읽는 중 문제가 생겼어요. 파일이 손상되지 않았는지 확인해 주세요.");
    }
  }

  function reset() {
    setState("idle");
    setResult(null);
    setErrMsg("");
    if (fileRef.current) fileRef.current.value = "";
  }

  // 안전선 계산 (공시가가 함께 넘어온 경우만)
  const safety = (() => {
    if (state !== "done" || !propertyPrice || !result) return null;
    const senior = result.seniorClaim.activeMaxClaimTotal || 0;
    // HUG 공식: (채권최고액 + 전세보증금) / 시세 ≤ 80%
    // 여기선 공시가 기준 참고치. 전세금은 사용자가 별도 입력해야 완성.
    return { senior, price: propertyPrice };
  })();

  const riskInfo = {
    CLEAN: { icon: "✅", label: "현재 유효한 위험 권리 없음", cls: "clean" },
    HAS_RIGHTS: { icon: "📋", label: "근저당 등 권리 있음 — 확인 필요", cls: "has" },
    HIGH: { icon: "⚠️", label: "압류·가처분 등 위험 권리 있음", cls: "high" },
    CRITICAL: { icon: "🚨", label: "경매 진행 등 심각한 위험", cls: "critical" },
  };

  return (
    <div className="registry">
      <div className="reg-head">
        <h3>등기부 선순위 확인</h3>
        <p className="reg-sub">
          인터넷등기소에서 발급한 등기부 PDF를 올리면, 근저당·압류 등 선순위 권리를
          확인해요. <strong>파일은 이 브라우저에서만 분석되고 서버로 전송되지 않아요.</strong>
        </p>
      </div>

      {state === "idle" && (
        <label className="reg-drop">
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            onChange={handleFile}
            style={{ display: "none" }}
          />
          <span className="reg-drop-icon">📄</span>
          <span className="reg-drop-text">등기부 PDF 선택</span>
          <span className="reg-drop-hint">텍스트가 포함된 발급 PDF만 (스캔·사진 불가)</span>
        </label>
      )}

      {state === "loading" && (
        <div className="reg-loading">
          <div className="reg-spinner" />
          <span>등기부를 분석하고 있어요…</span>
        </div>
      )}

      {state === "error" && (
        <div className="reg-error">
          <p>{errMsg}</p>
          <button className="reg-retry" onClick={reset}>다시 시도</button>
        </div>
      )}

      {state === "done" && result && (
        <div className="reg-result">
          {/* 종합 위험도 */}
          <div className={"reg-risk " + (riskInfo[result.riskLevel]?.cls || "")}>
            <span className="reg-risk-icon">{riskInfo[result.riskLevel]?.icon}</span>
            <span className="reg-risk-label">{riskInfo[result.riskLevel]?.label}</span>
          </div>

          {/* 부동산 정보 */}
          {result.property.address && (
            <div className="reg-addr">{result.property.address}</div>
          )}

          {/* 소유자 (신탁이면 경고) */}
          {result.owner && result.owner.name && (
            <div className={"reg-owner" + (result.owner.isTrust ? " trust" : "")}>
              <span className="reg-owner-label">등기부상 소유자</span>
              <span className="reg-owner-name">{result.owner.name}</span>
              {result.owner.isTrust && (
                <p className="reg-owner-warn">
                  ⚠️ 이 집은 <strong>신탁</strong>되어 있어요. 소유자가 신탁회사(수탁자)라서,
                  집주인과 계약해도 <strong>수탁자 동의 없이는 보증금을 지키기 어려울 수 있어요.</strong>
                  반드시 신탁원부를 확인하세요.
                </p>
              )}
            </div>
          )}

          {/* 근저당 (선순위 채권최고액) */}
          <div className="reg-section">
            <div className="reg-section-title">선순위 채권최고액 (등기부 표시)</div>
            {result.seniorClaim.mortgages.length > 0 ? (
              <>
                <div className="reg-amount">
                  {won(result.seniorClaim.activeMaxClaimTotal)}원
                </div>
                {result.seniorClaim.mortgages.map((m, i) => (
                  <div className="reg-item" key={i}>
                    {m.rank}번 근저당 · {won(m.amount)}원
                    {m.creditor ? ` · ${m.creditor}` : ""}
                  </div>
                ))}
                {result.seniorClaim.allMortgages
                  .filter((m) => m.cancelled)
                  .map((m, i) => (
                    <div className="reg-item cancelled" key={"c" + i}>
                      {m.rank}번 {won(m.amount)}원 (말소됨 — 제외)
                    </div>
                  ))}
              </>
            ) : (
              <div className="reg-empty-note">
                현재 유효한 근저당이 없어요
                {result.seniorClaim.allMortgages.length > 0 && " (과거 근저당은 모두 말소됨)"}
              </div>
            )}
          </div>

          {/* 요약 페이지 교차검증 */}
          {result.crossCheck?.available && (
            <div className={"reg-verify" + (result.crossCheck.ok ? " ok" : " warn")}>
              {result.crossCheck.ok ? (
                <>✓ 등기부 뒤쪽 <strong>주요 등기사항 요약</strong>과 대조해 같은 값임을 확인했어요.</>
              ) : (
                <>⚠️ 본문과 요약 페이지의 값이 달라요. 원본을 직접 확인해 주세요.
                  {!result.crossCheck.mortgageMatch && (
                    <span className="reg-verify-detail">
                      요약 기준 채권최고액: {won(result.crossCheck.summaryMortgageTotal)}원
                    </span>
                  )}
                </>
              )}
            </div>
          )}

          {/* 위험 플래그 */}
          {result.riskFlags.length > 0 && (
            <div className="reg-section">
              <div className="reg-section-title">현재 유효한 위험 권리</div>
              {result.riskFlags.map((f, i) => (
                <div className={"reg-flag sev-" + f.severity.toLowerCase()} key={i}>
                  {f.section} {f.rank}번 · {f.kind}
                  {f.amount ? ` · ${won(f.amount)}원` : ""}
                </div>
              ))}
            </div>
          )}

          {/* 말소된 위험 (참고) */}
          {result.cancelledFlags.length > 0 && (
            <details className="reg-cancelled-box">
              <summary>말소된 권리 {result.cancelledFlags.length}건 (참고)</summary>
              {result.cancelledFlags.map((f, i) => (
                <div className="reg-item cancelled" key={i}>
                  {f.section} {f.rank}번 {f.kind} → 말소됨
                </div>
              ))}
            </details>
          )}

          {/* 안전선 (공시가 연계 시) */}
          {safety && (
            <div className="reg-safety">
              <div className="reg-section-title">참고: 공시가 대비</div>
              <div className="reg-safety-row">
                <span>선순위 채권최고액</span>
                <span>{won(safety.senior)}원</span>
              </div>
              <div className="reg-safety-row">
                <span>이 세대 공시가격</span>
                <span>{won(safety.price)}원</span>
              </div>
              <p className="reg-safety-hint">
                깡통전세 판단은 시세 기준이에요. (채권최고액 + 내 전세보증금) ÷ 시세가
                80% 이하인지 확인하세요. 여기 공시가는 참고용이에요.
              </p>
            </div>
          )}

          {/* 면책 */}
          <p className="reg-disclaimer">{result.disclaimer}</p>

          <button className="reg-retry" onClick={reset}>다른 등기부 확인</button>
        </div>
      )}
    </div>
  );
}
