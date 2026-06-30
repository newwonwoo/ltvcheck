import { useEffect, useRef } from "react";
import { eok } from "../utils/format.js";

// 작년·올해 공시가를 곡선으로 잇는 시그니처 그래프.
// 증가면 우측 점이 위로(허니색), 감소면 아래로(로즈색).
export default function ValueJourney({ last, now }) {
  const pathRef = useRef(null);

  const W = 440;
  const H = 150;
  const padX = 64;
  const up = now >= last;
  const lift = Math.min(46, Math.max(20, (Math.abs(now - last) / Math.max(last, 1)) * 420));
  const baseY = H / 2;
  const yL = up ? baseY + lift / 2 : baseY - lift / 2;
  const yR = up ? baseY - lift / 2 : baseY + lift / 2;
  const xL = padX;
  const xR = W - padX;
  const cx1 = xL + (xR - xL) * 0.42;
  const cx2 = xL + (xR - xL) * 0.58;
  const d = `M ${xL} ${yL} C ${cx1} ${yL}, ${cx2} ${yR}, ${xR} ${yR}`;
  const col = up ? "var(--honey)" : "var(--rose)";

  // 곡선 그리기 애니메이션
  useEffect(() => {
    const p = pathRef.current;
    if (!p) return;
    const reduce = window.matchMedia("(prefers-reduced-motion:reduce)").matches;
    if (reduce) return;
    const len = p.getTotalLength();
    p.style.strokeDasharray = len;
    p.style.strokeDashoffset = len;
    // reflow 강제
    p.getBoundingClientRect();
    p.style.transition = "stroke-dashoffset 1.05s cubic-bezier(.22,.9,.3,1)";
    p.style.strokeDashoffset = "0";
  }, [last, now]);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="fade" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor={col} stopOpacity="0.35" />
          <stop offset="1" stopColor={col} stopOpacity="1" />
        </linearGradient>
      </defs>
      <line x1={xL} y1={26} x2={xL} y2={H - 26} stroke="var(--line)" strokeWidth="1" strokeDasharray="3 4" />
      <line x1={xR} y1={26} x2={xR} y2={H - 26} stroke="var(--line)" strokeWidth="1" strokeDasharray="3 4" />
      <path ref={pathRef} d={d} fill="none" stroke="url(#fade)" strokeWidth="3.4" strokeLinecap="round" />
      <circle cx={xL} cy={yL} r="6.5" fill="#fff" stroke={col} strokeWidth="3" />
      <circle cx={xR} cy={yR} r="7.5" fill={col} stroke="#fff" strokeWidth="3" />
      <text
        x={xL}
        y={yL + (up ? 28 : -18)}
        textAnchor="middle"
        fontFamily="Gowun Batang, serif"
        fontWeight="700"
        fontSize="17"
        fill="var(--ink-2)"
      >
        {eok(last)}
      </text>
      <text
        x={xR}
        y={yR + (up ? -18 : 28)}
        textAnchor="middle"
        fontFamily="Gowun Batang, serif"
        fontWeight="700"
        fontSize="19"
        fill="var(--ink)"
      >
        {eok(now)}
      </text>
    </svg>
  );
}
